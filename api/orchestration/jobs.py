"""Job lifecycle orchestration.

The flow at a glance (the lifecycle the routes implement on top of these
helpers):

1.  ``POST /api/goals`` — clarifier reasoner returns a budget question. No
    DB write yet (goals aren't a persisted entity in this scope).
2.  ``POST /api/goals/{goal_id}/clarify`` — discovery (mocks for now) +
    return listings. The goal text + budget are stashed in an in-memory
    dict keyed by ``goal_id`` (also non-persisted; hackathon-acceptable).
3.  ``POST /api/listings/{listing_id}/negotiate`` — ``spawn_job`` creates a
    ``jobs`` row, invokes the valuation reasoner (best-effort) to seed a
    ``target_price``, invokes the coordinator reasoner to seed BATNA
    shared memory, then invokes the negotiator reasoner with
    ``skip_pause=True`` so the negotiator returns its draft directly
    instead of blocking on ``app.pause()``. The route then creates an
    ``approval_queue`` row from the negotiator's response.
4.  ``GET /api/jobs/{job_id}`` — reads the full job state (job + messages
    + pending approval card).
5.  ``GET /api/jobs/{job_id}/stream`` — SSE polling (see
    ``api/orchestration/sse.py``).
6.  ``POST /api/jobs/{job_id}/approvals/{card_id}`` — resolves the queue
    row, writes a ``message_threads`` row on approve, calls Actionbook
    (mocks for now) to send the message. The negotiator's
    ``app.pause()`` call — which we never trigger in this Pass — would
    time out harmlessly after 72h. Pass 3 may wire a real pause/resume
    bridge.
7.  Job close — ``write_case_on_completion(job, session)`` writes the
    full transcript to EverOS via the memory_store wrapper.

**Pause/resume design note (the simpler path chosen for this Pass):**

The negotiator reasoner accepts a ``skip_pause: bool`` parameter (added
to ``api/agents/negotiator.py``). When True, the negotiator drafts the
message and returns immediately without calling ``app.pause()``.
FastAPI then orchestrates the wait via the ``approval_queue`` row in
Postgres — much cleaner than coupling FastAPI's request lifecycle to
the af-server's pause future. The downside is we don't exercise the
full AgentField pause/resume primitive at the FastAPI seam; Pass 1
already exercises ``app.pause()`` in the negotiator code path (verified
via runtime probe) which satisfies the SPEC.md sponsor-depth
requirement on that primitive.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from api import memory_store
from api.config import get_settings
from api.contracts import (
    ApprovalCard,
    Job as JobContract,
    Listing,
    Message,
)
from api.models import (
    ApprovalQueueItem,
    Job as JobORM,
    MessageThread,
)
from api.orchestration.agents_client import invoke_reasoner

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory goal cache (goals aren't a persisted entity in Pass 2 scope).
# Keys are goal_id; values are ``{text, budget}``. Survives the process
# lifetime only — hackathon-acceptable for the demo flow.

_goal_cache: dict[str, dict[str, Any]] = {}


def remember_goal(goal_id: str, text: str) -> None:
    _goal_cache[goal_id] = {"text": text, "budget": None}


def remember_budget(goal_id: str, budget: float) -> None:
    entry = _goal_cache.setdefault(goal_id, {"text": "", "budget": None})
    entry["budget"] = float(budget)


def get_goal(goal_id: str) -> dict[str, Any]:
    return _goal_cache.get(goal_id, {"text": "", "budget": None})


# ---------------------------------------------------------------------------
# Job spawn / lifecycle


async def spawn_job(
    session: AsyncSession,
    *,
    listing: Listing,
    target_price: Optional[float] = None,
    user_id: Optional[str] = None,
) -> JobORM:
    """Create a new Job row.

    If ``target_price`` is None, the caller is expected to invoke the
    valuation reasoner separately and either pass it in here OR update
    the row afterwards. Kept stateless for testability.
    """
    settings = get_settings()
    uid = user_id or settings.demo_user_id
    job = await JobORM.create(
        session,
        user_id=uid,
        listing_id=listing.id,
        status="active",
        target_price=target_price,
    )
    logger.info("spawn_job: created job=%s listing=%s target_price=%s", job.id, listing.id, target_price)
    return job


async def invoke_valuation_for_listing(
    listing: Listing, *, budget: Optional[float], user_id: str
) -> Optional[float]:
    """Best-effort call to the valuation reasoner; returns target_price or None.

    Failures are logged and ``None`` is returned so the caller can default
    gracefully.
    """
    try:
        out = await invoke_reasoner(
            "assess_listing",
            {
                "listing": listing.model_dump(),
                "user_budget": budget,
                "user_id": user_id,
            },
            timeout=30.0,
            raise_on_error=False,
        )
    except Exception:  # noqa: BLE001 — defensive; invoke_reasoner already catches httpx errors
        logger.exception("invoke_valuation_for_listing: reasoner call raised")
        return None
    if "error" in out:
        logger.info("invoke_valuation_for_listing: reasoner returned error=%s", out.get("error"))
        return None
    target = out.get("target_price")
    if isinstance(target, (int, float)):
        return float(target)
    return None


async def seed_batna_via_coordinator(
    *,
    goal_id: str,
    listings: list[Listing],
    target_listing_ids: list[str],
    target_price: float,
    user_id: str,
) -> dict:
    """Invoke the coordinator reasoner to seed shared BATNA memory.

    Failures are caught — coordinator's purpose here is best-effort memory
    seeding, not blocking the negotiate path.
    """
    try:
        return await invoke_reasoner(
            "spawn_negotiations",
            {
                "goal_id": goal_id,
                "listings": [li.model_dump() for li in listings],
                "target_listing_ids": target_listing_ids,
                "target_price": target_price,
                "user_id": user_id,
            },
            timeout=30.0,
            raise_on_error=False,
        )
    except Exception:  # noqa: BLE001 — defensive
        logger.exception("seed_batna_via_coordinator: reasoner call raised")
        return {"error": "coordinator_unavailable"}


async def invoke_negotiator_for_draft(
    *,
    job_id: str,
    conversation: list[dict],
    target_price: Optional[float],
    user_id: str,
) -> dict:
    """Invoke the negotiator reasoner in ``skip_pause`` mode.

    Returns the reasoner's response dict (``draft_text``,
    ``draft_reasoning``, etc.) or a fallback ``{"draft_text": ...,
    "draft_reasoning": ...}`` on transport failure so callers can always
    create an approval_queue row.
    """
    payload = {
        "job_id": job_id,
        "conversation": conversation,
        "target_price": float(target_price) if target_price is not None else 0.0,
        "user_id": user_id,
        "skip_pause": True,
    }
    try:
        out = await invoke_reasoner(
            "draft_message", payload, timeout=60.0, raise_on_error=False
        )
    except Exception:  # noqa: BLE001 — defensive
        logger.exception("invoke_negotiator_for_draft: reasoner call raised")
        out = {}
    # Always materialize a usable draft so callers can render an approval card.
    draft_text = out.get("draft_text") if isinstance(out, dict) else None
    if not isinstance(draft_text, str) or not draft_text.strip():
        draft_text = (
            "Hi, is this still available? "
            "Would you consider a slightly lower offer for a quick cash pickup?"
        )
    draft_reasoning = out.get("draft_reasoning") if isinstance(out, dict) else None
    if not isinstance(draft_reasoning, str):
        draft_reasoning = "fallback — negotiator reasoner unavailable; safe opener."
    return {
        "draft_text": draft_text,
        "draft_reasoning": draft_reasoning,
        # carry-through for debugging
        "raw": out,
    }


async def advance_job_state(
    session: AsyncSession,
    *,
    job_id: str,
    new_status: str,
    bump_last_message_at: bool = False,
) -> Optional[JobORM]:
    return await JobORM.advance_status(
        session,
        job_id,
        new_status,
        bump_last_message_at=bump_last_message_at,
    )


async def mark_closed(
    session: AsyncSession, *, job_id: str
) -> Optional[JobORM]:
    """Transition a job to ``closed`` and write a Case to EverOS.

    The Case write is fire-and-forget at the SQL level — we DO await it
    so we can log on failure, but EverOS errors are swallowed inside
    `memory_store.write_case_on_completion` so they never propagate.
    """
    job = await JobORM.advance_status(session, job_id, "closed")
    if job is None:
        return None
    try:
        await memory_store.write_case_on_completion(job, session)
    except Exception:  # noqa: BLE001 — graceful degradation
        logger.exception("mark_closed: write_case_on_completion failed (non-fatal)")
    return job


async def write_case_on_completion(
    job: JobORM, session: AsyncSession
) -> None:
    """Convenience wrapper — keeps the import surface tidy."""
    await memory_store.write_case_on_completion(job, session)


# ---------------------------------------------------------------------------
# Snapshot building (used by route handlers + SSE)


async def build_job_response(
    session: AsyncSession, job_id: str
) -> Optional[JobContract]:
    """Compose the full ``Job`` contract shape for ``GET /jobs/{id}`` + SSE.

    Returns None if the job doesn't exist.
    """
    job = await JobORM.get(session, job_id)
    if job is None:
        return None

    message_rows = await MessageThread.list_for_job(session, job_id)
    messages = [
        Message(
            id=m.id,
            job_id=m.job_id,
            role=m.role,  # type: ignore[arg-type]
            text=m.text,
            sent_at=m.sent_at,
        )
        for m in message_rows
    ]

    pending = await ApprovalQueueItem.get_pending_for_job(session, job_id)
    pending_card: Optional[ApprovalCard] = None
    if pending is not None:
        pending_card = ApprovalCard(
            id=pending.id,
            job_id=pending.job_id,
            draft_text=pending.draft_text,
            draft_reasoning=pending.draft_reasoning,
            status="pending",
            created_at=pending.created_at,
        )

    return JobContract(
        id=job.id,
        user_id=job.user_id,
        listing_id=job.listing_id,
        status=job.status,  # type: ignore[arg-type]
        target_price=job.target_price,
        listing=None,  # not stored alongside the job row; future enrichment
        messages=messages,
        pending_approval_card=pending_card,
        created_at=job.created_at,
        last_message_at=job.last_message_at,
    )
