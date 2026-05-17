"""Job lifecycle orchestration.

The flow at a glance:

1.  ``POST /api/goals`` — clarifier reasoner returns a budget question. No
    DB write yet (goals aren't a persisted entity in this scope).
2.  ``POST /api/goals/{goal_id}/clarify`` — discovery + return listings.
    The goal text + budget are stashed in an in-memory dict keyed by
    ``goal_id`` (not persisted).
3.  ``POST /api/listings/{listing_id}/negotiate`` — ``spawn_job`` creates a
    ``jobs`` row + invokes valuation + seeds BATNA via the coordinator,
    then fires the negotiator in the background (``asyncio.create_task``).
    The route returns ``{job_id}`` immediately. The negotiator runs in
    the agent server, drafts the message, calls ``app.pause()`` which
    POSTs to FastAPI's bridge router → notification → SSE push to UI.
4.  User approves via ``POST /api/approvals/{approval_request_id}`` → the
    approvals route bridges the decision back to the agent's
    ``/webhooks/approval`` → the paused reasoner's future resolves and it
    finishes processing (writing the message_threads row + dispatching
    via the browser-use agent over Browserbase CDP).
5.  ``GET /api/jobs/{job_id}`` — reads the full job state.
6.  ``GET /api/jobs/{job_id}/stream`` — SSE polling.
7.  Job close — ``write_case_on_completion(job, session)`` writes the
    full transcript to EverOS via the memory_store wrapper.
8.  ``POST /api/jobs/{job_id}/finalize-close`` (Phase F) — sends the
    yes-message to the chosen seller, dispatches the hardcoded
    ``_DECLINE_TEMPLATE`` to every sibling job in the same hunt, then
    marks the chosen Job + parent Hunt closed and writes a Case to EverOS.

**Pause/resume bridge.** Reasoners use ``app.pause()`` natively; the
bridge router (``api/routes/agent_bridge.py``) accepts the control-plane
callbacks AgentField's SDK speaks. The negotiator's ``skip_pause``
param is kept for backwards compatibility with tests, but no
orchestration caller sets it to True anymore.

**Per-job lifecycle.** ``run_job_lifecycle`` is the per-Job coroutine
spawned by the hunt's pick-phase. It drives a single round: invoke
negotiator (which pauses for approval) → on approve, send via the
browser-use agent over the user's Browserbase context + persist
message → advance the Job to ``awaiting_seller_reply`` and EXIT. The
lifecycle does NOT poll for replies — Browserbase quota is precious,
so reply fetching is user-triggered via
``POST /api/jobs/{job_id}/check-replies`` (see ``api/routes/jobs.py``).

**Deterministic close.** The lifecycle does NOT auto-detect when a deal
is closed. Close happens exclusively when the user picks the
``"close_deal"`` decision on an approval; the route handler
(``api/routes/approvals.py::decide_approval_by_request_id``) writes
the Case to EverOS + emits the ``deal_closed`` notification then.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import memory_store
from api.contracts import (
    ApprovalCard,
    Job as JobContract,
    Listing,
    Message,
)
from api.db import AsyncSessionLocal
from api.models import (
    ApprovalQueueItem,
    Job as JobORM,
    ListingCache,
    MessageThread,
)
from api.orchestration.agents_client import invoke_reasoner

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory goal cache (goals aren't a persisted entity).
# Keys are goal_id; values are ``{text, budget}``. Survives the process
# lifetime only.

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
    user_id: str,
) -> JobORM:
    """Create a new Job row.

    If ``target_price`` is None, the caller is expected to invoke the
    valuation reasoner separately and either pass it in here OR update
    the row afterwards. Kept stateless for testability.

    ``user_id`` is a required ``str(User.id)`` UUID — there is no demo
    fallback. Routes resolve it from the ``current_user`` dependency.
    """
    if not user_id:
        raise ValueError("spawn_job requires a non-empty user_id")
    uid = user_id
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


# ---------------------------------------------------------------------------
# BATNA context — full conversation history for OTHER active jobs
# in the same hunt. Replaces the price-shape-only ``app.memory[batna:*]``
# read that the negotiator used to do.
#
# This is the cross-leverage signal that lets the agent draft messages
# like "I have another seller at $199 — can you match?". The shared
# memory bus was the wrong abstraction; the canonical conversation
# history lives in Postgres and is rebuilt per draft call here.


_BATNA_ACTIVE_STATUSES = (
    "active",
    "awaiting_seller_reply",
    "awaiting_user_approval",
)


async def get_batna_context_for_hunt(
    hunt_id: Optional[str],
    exclude_job_id: str,
    session: AsyncSession,
) -> list[dict]:
    """Pull full conversation history for every OTHER active job in this hunt.

    Excludes the job_id passed in (that's the one currently negotiating).
    Only includes jobs in non-terminal status (active, awaiting_seller_reply,
    awaiting_user_approval).

    Returns a list of dicts shaped for the negotiator prompt:

    ``[{job_id, listing_title, marketplace, asking_price, target_price,
        status, conversation: [{role, text, sent_at}, ...]}]``

    Returns ``[]`` when ``hunt_id`` is None (legacy ``/negotiate``
    one-off jobs without a parent hunt). Errors are logged + swallowed
    so a flaky DB read never breaks the negotiator path.
    """
    if not hunt_id:
        return []
    try:
        result = await session.execute(
            select(JobORM).where(
                JobORM.hunt_id == hunt_id,
                JobORM.id != exclude_job_id,
                JobORM.status.in_(_BATNA_ACTIVE_STATUSES),
            )
        )
        sibling_jobs = list(result.scalars().all())
    except Exception:  # noqa: BLE001 — best-effort
        logger.exception(
            "get_batna_context_for_hunt: sibling job lookup failed hunt=%s",
            hunt_id,
        )
        return []

    if not sibling_jobs:
        return []

    context: list[dict] = []
    for job in sibling_jobs:
        # Pull the message thread for this sibling job.
        try:
            messages = await MessageThread.list_for_job(session, job.id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "get_batna_context_for_hunt: thread lookup failed job=%s",
                job.id,
            )
            messages = []

        # Join the listing cache for marketplace / title / asking price.
        listing_title = ""
        marketplace = ""
        asking_price: Optional[float] = None
        try:
            cache_rows = await session.execute(
                select(ListingCache).where(
                    ListingCache.listing_id == job.listing_id
                )
            )
            cache_row = cache_rows.scalars().first()
            if cache_row is not None:
                listing_title = cache_row.title or ""
                marketplace = cache_row.marketplace or ""
                if cache_row.price_cents is not None:
                    asking_price = float(cache_row.price_cents) / 100.0
        except Exception:  # noqa: BLE001
            logger.exception(
                "get_batna_context_for_hunt: listings_cache lookup failed "
                "listing=%s",
                job.listing_id,
            )

        context.append(
            {
                "job_id": str(job.id),
                "listing_title": listing_title,
                "marketplace": marketplace,
                "asking_price": asking_price,
                "target_price": job.target_price,
                "status": job.status,
                "conversation": [
                    {
                        "role": m.role,
                        "text": m.text,
                        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                    }
                    for m in messages
                ],
            }
        )

    return context


async def invoke_negotiator_for_draft(
    *,
    job_id: str,
    conversation: list[dict],
    target_price: Optional[float],
    user_id: str,
    batna_context: Optional[list[dict]] = None,
    listing_category: str = "",
    listing_region: str = "",
) -> dict:
    """Invoke the negotiator reasoner and return the response shape.

    The negotiator uses ``app.pause()`` natively. This invocation will
    BLOCK until the pause resolves, so callers that need a
    fire-and-forget shape should use
    ``spawn_negotiator_in_background`` instead.

    ``batna_context`` is the list returned by ``get_batna_context_for_hunt``
    — passed through to the reasoner so it can use other active
    negotiations as leverage. Defaults to ``[]`` when omitted.

    ``listing_category`` + ``listing_region`` are passed through to the
    reasoner so it can fetch matching past-Cases from EverOS via
    ``list_top_cases_for_draft``. Defaults to empty strings.

    Returns the reasoner's response dict (``draft_text``,
    ``draft_reasoning``, etc.) or a fallback ``{"draft_text": ...,
    "draft_reasoning": ...}`` on transport failure so callers can always
    materialize an approval card.
    """
    payload = {
        "job_id": job_id,
        "conversation": conversation,
        "target_price": float(target_price) if target_price is not None else 0.0,
        "user_id": user_id,
        "batna_context": batna_context or [],
        "listing_category": listing_category or "",
        "listing_region": listing_region or "",
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


async def invoke_classifier_for_job(job_id: str) -> Optional[dict]:
    """Run the end-of-negotiation classifier reasoner against a job's state.

    Phase E of the ancient-brewing-brooks plan. Called as a background
    task after every new buyer message (in
    ``api/routes/approvals.py:_apply_post_decision``) and after every
    new seller reply (in ``api/routes/jobs.py:check_replies``).

    Loads the Job + its full message thread + the listing details +
    target_price, hands it to the classifier reasoner, then persists
    the verdict to ``Job.ready_to_close`` /
    ``Job.close_signal_reason`` / ``Job.suggested_close_price``. On
    ``ready_to_close=True`` it also emits a
    ``negotiation_ready_to_close`` notification so the UI surfaces
    "ready to close" without waiting on the next poll.

    Returns the classifier's response dict on success, or ``None`` on
    any failure (the classifier itself returns a safe ``ready_to_close=
    False`` fallback rather than raising, so a ``None`` return here
    means we couldn't even load the job).
    """
    try:
        async with AsyncSessionLocal() as session:
            job = await JobORM.get(session, job_id)
            if job is None:
                logger.warning(
                    "invoke_classifier_for_job: job=%s not found", job_id
                )
                return None
            user_id = job.user_id
            target_price = job.target_price
            messages = await MessageThread.list_for_job(session, job_id)
            conversation = [
                {
                    "role": m.role,
                    "text": m.text,
                    "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                }
                for m in messages
            ]
            listing_dict: dict = {}
            try:
                cache_rows = await session.execute(
                    select(ListingCache).where(
                        ListingCache.listing_id == job.listing_id
                    )
                )
                cache_row = cache_rows.scalars().first()
                if cache_row is not None:
                    listing_dict = {
                        "id": cache_row.listing_id,
                        "title": cache_row.title or "",
                        "marketplace": cache_row.marketplace or "",
                        "price": (
                            cache_row.price_cents / 100.0
                            if cache_row.price_cents is not None
                            else 0.0
                        ),
                        "url": cache_row.url or "",
                        "description": cache_row.description or "",
                    }
            except Exception:  # noqa: BLE001 — listing context is best-effort
                logger.exception(
                    "invoke_classifier_for_job: listing lookup failed job=%s",
                    job_id,
                )

        response = await invoke_reasoner(
            "classify_negotiation_state",
            {
                "conversation": conversation,
                "listing": listing_dict,
                "target_price": float(target_price)
                if target_price is not None
                else None,
                "user_id": user_id,
            },
            timeout=60.0,
            raise_on_error=False,
        )
        if not isinstance(response, dict):
            return None

        ready_to_close = bool(response.get("ready_to_close"))
        reason = response.get("reason")
        if not isinstance(reason, str):
            reason = None
        suggested_raw = response.get("suggested_close_price")
        suggested_close_price: Optional[float]
        if isinstance(suggested_raw, (int, float)):
            suggested_close_price = float(suggested_raw)
        else:
            suggested_close_price = None

        async with AsyncSessionLocal() as session:
            await JobORM.update_readiness(
                session,
                job_id,
                ready_to_close=ready_to_close,
                close_signal_reason=reason,
                suggested_close_price=suggested_close_price,
            )
            await session.commit()

        # Emit a heads-up notification on the transition to ready. The UI
        # already polls the deal page, but a notification surfaces in the
        # bell + toast immediately.
        if ready_to_close:
            try:
                from api import notifications as notif_queue
                from api.models import Notification

                async with AsyncSessionLocal() as session:
                    notif = await Notification.create(
                        session,
                        user_id=user_id,
                        kind="info",
                        title="Negotiation ready to close",
                        body=(
                            reason
                            or "Goti thinks this deal is at a natural close-point."
                        ),
                        target_href=f"/deal/{job_id}",
                        job_id=job_id,
                        payload={
                            "kind_tag": "negotiation_ready_to_close",
                            "job_id": job_id,
                            "suggested_close_price": suggested_close_price,
                            "reason": reason,
                        },
                    )
                    await session.commit()
                    await notif_queue.enqueue(notif.to_event_dict())
            except Exception:  # noqa: BLE001 — notification best-effort
                logger.exception(
                    "invoke_classifier_for_job: ready_to_close notif failed job=%s",
                    job_id,
                )

        return response
    except Exception:  # noqa: BLE001 — classifier is best-effort
        logger.exception(
            "invoke_classifier_for_job: classifier call raised job=%s", job_id
        )
        return None


def spawn_classifier_in_background(job_id: str) -> None:
    """Fire-and-forget the classifier reasoner.

    Called from approval-resolution + check-replies after a new message
    has been persisted. The classifier writes back to the Job row, so
    callers don't need the response — they just need the write to land
    eventually.

    Phase L — wrapped in the task registry so the frontend chat sees
    a "Reading negotiation state…" tile while the classifier is
    running.
    """
    import asyncio as _asyncio

    from api.orchestration import tasks as _task_registry

    async def _run_with_task() -> None:
        # Resolve hunt_id for the task registry (lookup is best-effort).
        hunt_id: Optional[str] = None
        try:
            async with AsyncSessionLocal() as s:
                job = await JobORM.get(s, job_id)
                if job is not None:
                    hunt_id = job.hunt_id
        except Exception:  # noqa: BLE001
            pass
        task_id = None
        try:
            task_id = _task_registry.start_task(
                kind="classifier",
                hunt_id=hunt_id,
                job_id=job_id,
                label="Reading negotiation state",
            )
        except Exception:  # noqa: BLE001
            task_id = None
        try:
            await invoke_classifier_for_job(job_id)
            if task_id:
                _task_registry.finish_task(task_id, status="completed")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "spawn_classifier_in_background: invocation failed job=%s",
                job_id,
            )
            if task_id:
                _task_registry.finish_task(
                    task_id, status="errored", summary=str(exc)
                )

    _asyncio.create_task(_run_with_task())


def spawn_negotiator_in_background(
    *,
    job_id: str,
    conversation: list[dict],
    target_price: Optional[float],
    user_id: str,
) -> None:
    """Fire-and-forget the negotiator so the HTTP request can return ``{job_id}``.

    The negotiator pauses internally (``app.pause()`` → bridge router
    → notification → user resolution → webhook → resume). Awaiting it
    here would block the negotiate request for the full
    ``expires_in_hours`` window — instead, kick it off as a background
    task and let the SSE notification stream surface the approval card.
    """
    import asyncio as _asyncio

    async def _run() -> None:
        try:
            await invoke_negotiator_for_draft(
                job_id=job_id,
                conversation=conversation,
                target_price=target_price,
                user_id=user_id,
            )
        except Exception:  # noqa: BLE001 — never let background errors crash the loop
            logger.exception(
                "spawn_negotiator_in_background: reasoner call failed job=%s",
                job_id,
            )

    _asyncio.create_task(_run())


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


# ---------------------------------------------------------------------------
# Per-job lifecycle (driven by Hunt's pick phase)
# ---------------------------------------------------------------------------


async def run_job_lifecycle_safe(
    *,
    job_id: str,
    listing: dict,
    valuation: dict,
) -> None:
    """Wrap ``run_job_lifecycle`` in a defensive try/except.

    All exceptions logged + the job marked ``cancelled`` so it doesn't
    sit forever in ``active`` after a coroutine crash.

    Phase L — wrapped in the task registry so the frontend chat
    surfaces "Drafting the next message…" while the negotiator runs.
    """
    from api.orchestration import tasks as _task_registry

    hunt_id: Optional[str] = None
    try:
        async with AsyncSessionLocal() as s:
            job = await JobORM.get(s, job_id)
            if job is not None:
                hunt_id = job.hunt_id
    except Exception:  # noqa: BLE001
        hunt_id = None

    task_id = None
    try:
        task_id = _task_registry.start_task(
            kind="negotiator_draft",
            hunt_id=hunt_id,
            job_id=job_id,
            label="Drafting the next message",
        )
    except Exception:  # noqa: BLE001
        task_id = None

    try:
        await run_job_lifecycle(job_id=job_id, listing=listing, valuation=valuation)
        if task_id:
            _task_registry.finish_task(task_id, status="completed")
    except Exception as exc:  # noqa: BLE001 — top-level lifecycle catch
        logger.exception("run_job_lifecycle errored job=%s", job_id)
        if task_id:
            _task_registry.finish_task(
                task_id, status="errored", summary=str(exc)
            )
        try:
            async with AsyncSessionLocal() as s:
                await JobORM.advance_status(s, job_id, "cancelled")
                await s.commit()
        except Exception:  # noqa: BLE001
            logger.exception("run_job_lifecycle_safe: cleanup failed job=%s", job_id)


async def spawn_job_draft(job_id: str) -> bool:
    """Spawn ``run_job_lifecycle_safe`` for ``job_id`` in the background.

    Phase D of the ancient-brewing-brooks plan — the negotiator no longer
    auto-fires on Job create. This helper is the entry point for the
    explicit "Start negotiating" click on the deal page (called from
    ``POST /api/jobs/{job_id}/draft-next``). Loads the Job + listing +
    minimal valuation, then dispatches the lifecycle as an
    ``asyncio.create_task`` so the route can return immediately.

    Returns True when the lifecycle was spawned; False when the job
    doesn't exist or its hunt has been deleted out from under it.
    """
    import asyncio as _asyncio

    from api.orchestration.hunts import register_hunt_task

    async with AsyncSessionLocal() as session:
        job = await JobORM.get(session, job_id)
        if job is None:
            return False
        listing_id = job.listing_id
        hunt_id = job.hunt_id
        target_price = job.target_price

        listing_dict: dict = {}
        try:
            cache_rows = await session.execute(
                select(ListingCache).where(
                    ListingCache.listing_id == listing_id
                )
            )
            cache_row = cache_rows.scalars().first()
            if cache_row is not None:
                listing_dict = dict(cache_row.raw_data or {})
                listing_dict.setdefault("id", listing_id)
                listing_dict.setdefault("marketplace", cache_row.marketplace)
                listing_dict.setdefault("title", cache_row.title or "")
                listing_dict.setdefault(
                    "price",
                    (cache_row.price_cents / 100.0)
                    if cache_row.price_cents is not None
                    else 0.0,
                )
                listing_dict.setdefault("url", cache_row.url or "")
        except Exception:  # noqa: BLE001 — listing context best-effort
            logger.exception(
                "spawn_job_draft: listing lookup failed job=%s", job_id
            )

    # Synthesise a minimal valuation — the negotiator pulls richer
    # numbers from its own LLM calls; this just seeds the lifecycle so
    # it doesn't 500 on a missing dict.
    asking_price = listing_dict.get("price") or 0.0
    valuation = {
        "target_price": float(target_price)
        if target_price is not None
        else (asking_price or 0.0) * 0.85,
        "fair_price_estimate": asking_price,
        "walk_away_price": asking_price,
        "reasoning": "user-initiated draft via /draft-next",
    }

    task = _asyncio.create_task(
        run_job_lifecycle_safe(
            job_id=job_id,
            listing=listing_dict,
            valuation=valuation,
        )
    )
    if hunt_id:
        register_hunt_task(hunt_id, task)
    return True


async def run_job_lifecycle(
    *,
    job_id: str,
    listing: dict,
    valuation: dict,
) -> None:
    """Drive a single negotiation round for a single Job, then exit.

    Steps:

    1. Invoke ``draft_message`` reasoner — it pauses internally on
       ``app.pause()`` for the user to approve the draft. The
       approval-resolution route POSTs to the agent webhook, the future
       resolves, and ``invoke_reasoner`` returns with ``approval_status``
       + ``sent_text`` (the approved text, possibly edited by the user).
    2. If approved, persist a buyer_agent message row + send via the
       browser-use agent over Browserbase CDP.
    3. Advance the Job to ``awaiting_seller_reply`` and EXIT.

    Reply fetching is explicitly user-triggered via
    ``POST /api/jobs/{job_id}/check-replies`` (see
    ``api/routes/jobs.py``). When the user clicks "Check for reply" the
    endpoint runs ONE browser-agent ``fetch_replies`` call against
    their Browserbase context; on a hit it persists the reply,
    re-advances the Job to ``active``, and spawns the negotiator for
    the next counter (which pauses for approval again). The cycle
    repeats per user-initiated check — never as a background poll.
    """
    # Load the job once to read user_id + hunt_id (immutable for the
    # lifecycle). Subsequent reads re-open the session per phase.
    async with AsyncSessionLocal() as s:
        job = await JobORM.get(s, job_id)
        if job is None:
            logger.error("run_job_lifecycle: job=%s not found", job_id)
            return
        user_id = job.user_id
        hunt_id = job.hunt_id

    target_price_raw = valuation.get("target_price")
    try:
        target_price: Optional[float] = (
            float(target_price_raw) if target_price_raw is not None else None
        )
    except (TypeError, ValueError):
        target_price = None

    conversation: list[dict] = []

    # ---- 1. Draft + pause for approval ----
    # Pull BATNA conversations for the OTHER active jobs in this hunt
    # before invoking the negotiator. The reasoner uses this list as
    # cross-leverage when drafting.
    try:
        async with AsyncSessionLocal() as s:
            batna_context = await get_batna_context_for_hunt(
                hunt_id=hunt_id, exclude_job_id=job_id, session=s
            )
    except Exception:  # noqa: BLE001 — BATNA is best-effort
        logger.exception(
            "run_job_lifecycle: batna context lookup raised job=%s",
            job_id,
        )
        batna_context = []

    # Pull category/region hints for past-lesson lookup.
    listing_category = ""
    listing_region = ""
    if isinstance(listing, dict):
        listing_category = str(listing.get("category") or "").strip()
        listing_region = str(listing.get("region") or listing.get("location") or "").strip()

    try:
        negotiator_response = await invoke_reasoner(
            "draft_message",
            {
                "job_id": job_id,
                "conversation": conversation,
                "target_price": float(target_price) if target_price is not None else 0.0,
                "user_id": user_id,
                "batna_context": batna_context,
                "listing_category": listing_category,
                "listing_region": listing_region,
                "skip_pause": True,
            },
            timeout=120.0,  # 2-min cap; draft_negotiation is one LLM call
            raise_on_error=False,
        )
    except Exception:  # noqa: BLE001 — surface to lifecycle as cancellation
        logger.exception(
            "run_job_lifecycle: negotiator reasoner call raised job=%s", job_id
        )
        negotiator_response = {}

    # With ``skip_pause=True``, the negotiator returns the draft
    # directly. We persist the ApprovalQueueItem ourselves; the
    # existing approval-resolution route (`POST /api/approvals/{id}`)
    # handles approve/reject + dispatch.
    draft_text_raw = (
        negotiator_response.get("draft_text")
        if isinstance(negotiator_response, dict)
        else None
    )
    draft_text = (
        draft_text_raw.strip()
        if isinstance(draft_text_raw, str)
        else ""
    )
    draft_reasoning = (
        negotiator_response.get("draft_reasoning")
        if isinstance(negotiator_response, dict)
        else None
    )
    approval_request_id_from_resp = (
        negotiator_response.get("approval_request_id")
        if isinstance(negotiator_response, dict)
        else None
    )
    if not draft_text:
        logger.warning(
            "run_job_lifecycle: job=%s no draft_text returned from "
            "negotiator (response=%r) — marking cancelled",
            job_id,
            negotiator_response,
        )
        async with AsyncSessionLocal() as s:
            await JobORM.advance_status(s, job_id, "cancelled")
            await s.commit()
        return

    # Write the ApprovalQueueItem so the deal page renders the draft.
    approval_request_id = (
        approval_request_id_from_resp
        or f"job-{job_id}-msg-{len(conversation)}"
    )
    logger.warning(
        "run_job_lifecycle: persisting ApprovalQueueItem job=%s "
        "approval_request_id=%s draft_len=%d",
        job_id,
        approval_request_id,
        len(draft_text),
    )
    try:
        async with AsyncSessionLocal() as s:
            await ApprovalQueueItem.create(
                s,
                job_id=job_id,
                draft_text=draft_text,
                draft_reasoning=(
                    draft_reasoning
                    if isinstance(draft_reasoning, str)
                    else None
                ),
                execution_id=None,
                agent_node_id="goti",
                agent_callback_url=None,
                approval_request_id=approval_request_id,
                request_payload={
                    "kind": "approval_needed",
                    "job_id": job_id,
                    "user_id": user_id,
                    "draft_text": draft_text,
                },
            )
            await s.commit()
    except Exception:  # noqa: BLE001
        logger.exception(
            "run_job_lifecycle: ApprovalQueueItem write failed job=%s "
            "— marking cancelled",
            job_id,
        )
        async with AsyncSessionLocal() as s:
            await JobORM.advance_status(s, job_id, "cancelled")
            await s.commit()
        return

    # Emit an ``approval_needed`` notification so the UI sees the draft
    # surface in real-time (the deal page slideover polls the deal-room
    # endpoint, but the notification also drives the inbox + toast).
    try:
        async with AsyncSessionLocal() as s:
            from api.models import Notification

            await Notification.create(
                s,
                user_id=user_id,
                kind="approval_needed",
                title="Approve outbound message",
                body=(
                    f'Goti drafted: "{draft_text[:120]}'
                    f'{("…" if len(draft_text) > 120 else "")}"'
                ),
                target_href=f"/c/{hunt_id}?deal={job_id}" if hunt_id else f"/c/{job_id}",
                hunt_id=hunt_id,
                job_id=job_id,
                approval_request_id=approval_request_id,
                payload={
                    "kind": "approval_needed",
                    "draft_text": draft_text,
                    "draft_reasoning": draft_reasoning,
                    "job_id": job_id,
                    "hunt_id": hunt_id,
                },
            )
            await s.commit()
    except Exception:  # noqa: BLE001
        logger.exception(
            "run_job_lifecycle: approval_needed notification write "
            "failed (non-fatal) job=%s",
            job_id,
        )

    # Job stays "active" — the user clicks Approve on the deal page,
    # which fires POST /api/approvals/{approval_request_id} and that
    # route handles message persist + browser-use dispatch + status
    # advance to ``awaiting_seller_reply``.
    logger.info(
        "run_job_lifecycle: draft persisted job=%s — awaiting user approval",
        job_id,
    )


# NOTE: ``_is_deal_closed`` and ``_extract_agreed_price`` were removed.
# Job close is now deterministic — driven by the user picking the
# ``"close_deal"`` decision in the approval UI, which calls
# ``Job.close_at_price`` + writes a Case via the route handler.
#
# NOTE: the previous background seller-reply poll helper was removed —
# it minted a fresh Browserbase session every cycle, which burned the
# free tier's session quota. Reply fetching is now user-triggered via
# ``POST /api/jobs/{job_id}/check-replies`` (see ``api/routes/jobs.py``).
# One fetch per user click; no background concurrency.


# ---------------------------------------------------------------------------
# Phase F — finalize-close + sibling decline fan-out
# ---------------------------------------------------------------------------
#
# Hardcoded short decline template the user picked during the planning
# round. Sent to every sibling Job in the same hunt when the user
# finalizes a close on the chosen Job — short, polite, neutral so it
# reads as one human message regardless of the conversation context.
_DECLINE_TEMPLATE = (
    "Hi, thanks for chatting — I went with another option. "
    "Best of luck with the listing!"
)


_FINALIZE_SIBLING_ACTIVE_STATUSES = (
    "active",
    "awaiting_seller_reply",
    "awaiting_user_approval",
)


async def _send_message_via_browser_agent(
    *,
    user_id: str,
    listing_id: str,
    text: str,
    hunt_id: Optional[str],
    job_id: str,
) -> Optional[str]:
    """Shared helper for finalize_close: send ``text`` over the user's BB context.

    Returns the dispatched ``MessageId`` (or empty/None when no link /
    URL is available). Mirrors ``api/routes/approvals.py::_dispatch_outbound``
    in spirit but lives here so the orchestration layer can call it from
    background tasks without circular imports through the routes module.

    Failures are logged + swallowed — the finalize-close path is best-
    effort on dispatch (we still mark the Job closed + write the Case so
    the user's "I'm done" intent isn't lost on a flaky browser session).
    """
    from api.integrations.browser_agent import actions as agent_actions
    from api.models import IntegrationAccountRow

    # Resolve listing url + marketplace from listings_cache.
    marketplace = "fb"
    listing_url = ""
    try:
        async with AsyncSessionLocal() as s:
            cache_rows = await s.execute(
                select(ListingCache).where(ListingCache.listing_id == listing_id)
            )
            row = cache_rows.scalars().first()
            if row is not None:
                marketplace = row.marketplace or "fb"
                listing_url = row.url or ""
    except Exception:  # noqa: BLE001 — best-effort
        logger.exception(
            "_send_message_via_browser_agent: ListingCache lookup failed listing=%s",
            listing_id,
        )

    if not listing_url:
        logger.info(
            "_send_message_via_browser_agent: no listing url for listing=%s; "
            "skipping dispatch",
            listing_id,
        )
        return None

    # Resolve Browserbase context: prefer the row matching the
    # listing's marketplace; fall back to any active row for the user.
    context_id: Optional[str] = None
    try:
        provider = "nextdoor" if marketplace == "nextdoor" else "fb"
        async with AsyncSessionLocal() as s:
            row = await IntegrationAccountRow.get(s, user_id, provider)
            if row and row.browserbase_context_id:
                context_id = row.browserbase_context_id
            else:
                active_rows = await IntegrationAccountRow.list_active_for_user(
                    s, user_id
                )
                for r in active_rows:
                    if r.browserbase_context_id:
                        context_id = r.browserbase_context_id
                        break
    except Exception:  # noqa: BLE001 — best-effort
        logger.exception(
            "_send_message_via_browser_agent: BB context lookup failed user=%s",
            user_id,
        )
        context_id = None

    if not context_id:
        logger.info(
            "_send_message_via_browser_agent: no BB context for user=%s; "
            "skipping dispatch",
            user_id,
        )
        return None

    try:
        return await agent_actions.send_message(
            context_id=context_id,
            listing_url=listing_url,
            listing_id=listing_id,
            message_text=text,
            marketplace=marketplace,
            hunt_id=hunt_id,
            job_id=job_id,
        )
    except Exception:  # noqa: BLE001 — dispatch failure non-fatal
        logger.exception(
            "_send_message_via_browser_agent: send_message raised job=%s",
            job_id,
        )
        return None


async def finalize_close(
    *,
    job_id: str,
    final_price: float,
    agreed_text: Optional[str] = None,
) -> dict:
    """Close a deal — send the yes-message + decline siblings + close hunt.

    Phase F of the ancient-brewing-brooks plan. Pre-conditions:
    - Job exists + is non-terminal.
    - ``Job.ready_to_close`` is True (the classifier reasoner has
      signalled this is a natural close-point).

    Steps:
    1. Persist + dispatch the buyer-agent yes-message to the chosen seller.
       When ``agreed_text`` is empty we synthesise a short confirmation
       from ``final_price``.
    2. Enumerate sibling Jobs in the same hunt with active statuses.
    3. For each sibling: persist a buyer-agent decline message
       (``_DECLINE_TEMPLATE``), advance to ``closed`` (final_price=None
       to distinguish from the chosen winner), dispatch sequentially.
    4. Mark the chosen Job ``closed`` + record ``final_price`` +
       bump ``last_message_at``.
    5. Mark the parent Hunt ``status="closed"`` + ``lifecycle_phase="closed"``.
    6. Write a Case to EverOS for the chosen Job
       (``memory_store.write_case_on_completion``).
    7. Emit a ``deal_closed`` notification.

    Returns ``{ok, job_id, hunt_id, siblings_declined}``. Raises
    ``ValueError`` when ``Job.ready_to_close`` is False or the job is
    already terminal — the route handler maps that to a 409.
    """
    from api import notifications as notif_queue
    from api.models import (
        Hunt as HuntORM,
        Notification,
    )
    from api.orchestration import tasks as _task_registry

    finalize_task_id: Optional[str] = None

    async with AsyncSessionLocal() as session:
        job = await JobORM.get(session, job_id)
        if job is None:
            raise ValueError(f"unknown job_id: {job_id}")
        if job.status in ("closed", "cancelled"):
            raise ValueError(f"job is {job.status}; cannot finalize close")
        if not bool(getattr(job, "ready_to_close", False)):
            raise ValueError(
                "job is not ready_to_close — classifier has not flagged this "
                "negotiation as a natural close-point"
            )

        user_id = job.user_id
        hunt_id = job.hunt_id
        listing_id = job.listing_id

        try:
            finalize_task_id = _task_registry.start_task(
                kind="finalize_close",
                hunt_id=hunt_id,
                job_id=job_id,
                label="Closing the deal",
                user_id=user_id,
            )
        except Exception:  # noqa: BLE001
            finalize_task_id = None

        # ---- 2. Enumerate siblings BEFORE we close the chosen job ----
        sibling_rows: list[JobORM] = []
        if hunt_id:
            try:
                result = await session.execute(
                    select(JobORM).where(
                        JobORM.hunt_id == hunt_id,
                        JobORM.id != job_id,
                        JobORM.status.in_(_FINALIZE_SIBLING_ACTIVE_STATUSES),
                    )
                )
                sibling_rows = list(result.scalars().all())
            except Exception:  # noqa: BLE001 — sibling lookup best-effort
                logger.exception(
                    "finalize_close: sibling enumeration failed hunt=%s",
                    hunt_id,
                )
                sibling_rows = []

        # ---- 1. Persist the yes-message on the chosen job ----
        confirmation_text = (
            agreed_text.strip()
            if isinstance(agreed_text, str) and agreed_text.strip()
            else f"Sounds good — happy to go ahead at ${int(round(final_price))}. "
            f"When works for pickup?"
        )
        await MessageThread.append(
            session,
            job_id=job_id,
            role="buyer_agent",
            text=confirmation_text,
        )

        # ---- 3. Persist decline messages on each sibling ----
        sibling_ids: list[tuple[str, str]] = []  # (sibling_job_id, sibling_listing_id)
        for sib in sibling_rows:
            try:
                await MessageThread.append(
                    session,
                    job_id=sib.id,
                    role="buyer_agent",
                    text=_DECLINE_TEMPLATE,
                )
                sibling_ids.append((sib.id, sib.listing_id))
            except Exception:  # noqa: BLE001 — best-effort
                logger.exception(
                    "finalize_close: sibling decline persist failed sib=%s",
                    sib.id,
                )

        # ---- 4. Mark the chosen job closed with final_price ----
        await JobORM.close_at_price(
            session,
            job_id=job_id,
            final_price=float(final_price),
        )

        # ---- 3b. Mark each sibling closed (final_price=None) ----
        for sib_id, _ in sibling_ids:
            try:
                await JobORM.advance_status(
                    session,
                    sib_id,
                    "closed",
                    bump_last_message_at=True,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "finalize_close: sibling status advance failed sib=%s",
                    sib_id,
                )

        # ---- 5. Close the parent hunt ----
        if hunt_id:
            try:
                await HuntORM.update_status(session, hunt_id, "closed")
                await HuntORM.update_lifecycle_phase(session, hunt_id, "closed")
            except Exception:  # noqa: BLE001 — best-effort
                logger.exception(
                    "finalize_close: hunt close failed hunt=%s", hunt_id
                )

        await session.commit()

        # Refresh the chosen job row for the Case write.
        closed_job = await JobORM.get(session, job_id)

    # ---- 1b. Dispatch the yes-message via browser-agent (sequential) ----
    await _send_message_via_browser_agent(
        user_id=user_id,
        listing_id=listing_id,
        text=confirmation_text,
        hunt_id=hunt_id,
        job_id=job_id,
    )

    # ---- 3c. Dispatch sibling declines sequentially (no parallel send) ----
    # Sequential because Browserbase's session semaphore is precious — a
    # parallel fan-out across N sibling jobs would exhaust it on bigger
    # hunts. The plan caps siblings at ~5 in practice, so latency is
    # bounded.
    for sib_id, sib_listing_id in sibling_ids:
        await _send_message_via_browser_agent(
            user_id=user_id,
            listing_id=sib_listing_id,
            text=_DECLINE_TEMPLATE,
            hunt_id=hunt_id,
            job_id=sib_id,
        )

    # ---- 6. Write Case to EverOS ----
    # NOTE: Phase G' replaced the transcript-dump Case with the analyzer-
    # generated structured Case. The new flow is: ``run_post_close_analysis``
    # spawns N parallel ``analyze_negotiation`` reasoner calls (one per
    # closed job) — each writes its own analyzed-Case to EverOS. The
    # legacy ``write_case_on_completion`` is preserved for direct callers
    # (tests) but the finalize-close path uses the analyzer instead.
    if closed_job is not None and hunt_id:
        try:
            import asyncio as _asyncio
            from api.orchestration.analyzer import run_post_close_analysis

            _asyncio.create_task(
                run_post_close_analysis(hunt_id=hunt_id, user_id=user_id)
            )
        except Exception:  # noqa: BLE001 — analyzer is best-effort
            logger.exception(
                "finalize_close: run_post_close_analysis spawn failed "
                "hunt=%s (non-fatal)",
                hunt_id,
            )

    # ---- 7. Emit deal_closed notification ----
    try:
        async with AsyncSessionLocal() as s:
            notif = await Notification.create(
                s,
                user_id=user_id,
                kind="deal_closed",
                title="Deal closed",
                body=(
                    f"Agreed at ${int(round(final_price))} — "
                    f"{len(sibling_ids)} other seller(s) auto-declined."
                ),
                target_href=f"/deal/{job_id}",
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "final_price": float(final_price),
                    "agreed_text": confirmation_text,
                    "siblings_declined": len(sibling_ids),
                },
            )
            await s.commit()
            await notif_queue.enqueue(notif.to_event_dict())
    except Exception:  # noqa: BLE001 — notification best-effort
        logger.exception(
            "finalize_close: deal_closed notif failed job=%s", job_id
        )

    if finalize_task_id:
        try:
            _task_registry.finish_task(
                finalize_task_id,
                status="completed",
                summary=f"Closed at ${int(round(final_price))}",
            )
        except Exception:  # noqa: BLE001
            pass

    return {
        "ok": True,
        "job_id": job_id,
        "hunt_id": hunt_id,
        "siblings_declined": len(sibling_ids),
    }
