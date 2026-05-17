"""Goals routes — user-facing goal endpoints.

These endpoints back the frontend's goal-entry flow on top of the Hunt
lifecycle (``api/orchestration/hunts.py``):

- ``POST /api/goals`` — accepts ``{text}`` (free-form goal) or
  ``{item, max_price, near, avoid, pickup_timing}`` (the frontend's
  ``BuyingBrief`` shape). Creates a ``hunts`` row + spawns the
  background lifecycle coroutine. Returns ``{ok, hunt_id, item}``
  immediately — the lifecycle's first pause (clarifier → budget) will
  arrive via SSE notification stream.
- ``POST /api/goals/{goal_id}/clarify`` — legacy alias preserved for
  backwards compat. New flows use the AgentField pause/resume bridge
  via ``POST /api/approvals/{id}`` with ``{feedback: {budget}}``.
- ``GET /api/goals/{hunt_id}/listings`` — returns the rich
  ``StreamAListing[]`` shape, sourced from the lifecycle's in-process
  valuations cache (with fallback to the ``listings_cache`` table for
  cross-instance reads).
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import current_user
from api.config import get_settings
from api.contracts import (
    ClarifyRequest,
    ClarifyResponse,
    CreateGoalRequest,
    CreateGoalResponse,
    Listing,
    ListingsResponse,
    StreamAListing,
)
from api.db import get_session
from api.integrations import discovery as integ_discovery
from api.memory_store import write_case
from api.models import Hunt, ListingCache, User
from api.orchestration import hunts as orch_hunts, jobs as orch_jobs
from api.orchestration.agents_client import invoke_reasoner
from api.rate_limit import limit as _rate_limit, limiter as _limiter  # noqa: F401
from api.routes.adapter import _to_stream_a_listing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["goals"])


# ---------------------------------------------------------------------------
# POST /api/goals — kick off a hunt lifecycle


class CreateGoalBody(BaseModel):
    """Loose body shape — accepts either ``text`` (free-form) or the
    full Stream-A ``BuyingBrief`` (item + filters).
    """

    text: str | None = None
    item: str | None = None
    max_price: int | None = None
    near: str | None = None
    avoid: str | None = None
    pickup_timing: str | None = None


def _goal_text_from_body(body: CreateGoalBody) -> str:
    """Compose the natural-language goal text the lifecycle sees.

    If only ``text`` is set, use it directly. If only ``item`` is set,
    inline the filters into a synthesized natural-language goal so the
    LLM has rich context. If both are set, prefer ``text`` (already NL).
    """
    if body.text and body.text.strip():
        return body.text.strip()
    if body.item and body.item.strip():
        parts: list[str] = [body.item.strip()]
        if body.max_price:
            parts.append(f"under ${int(body.max_price)}")
        if body.near and body.near.strip():
            parts.append(f"near {body.near.strip()}")
        if body.avoid and body.avoid.strip():
            parts.append(f"avoid {body.avoid.strip()}")
        if body.pickup_timing and body.pickup_timing.strip():
            parts.append(f"pickup {body.pickup_timing.strip()}")
        return " ".join(parts)
    return ""


@router.post("/goals")
@_rate_limit("10/minute")
async def create_goal(
    request: Request,
    body: CreateGoalBody = Body(default_factory=CreateGoalBody),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Spawn a hunt lifecycle for the user's goal.

    Returns immediately with ``{ok, hunt_id, item}``; the lifecycle runs
    in the background. The frontend listens on ``GET /api/notifications``
    (or its SSE counterpart) for the clarifier's budget question.
    """
    goal_text = _goal_text_from_body(body)
    if not goal_text:
        raise HTTPException(
            status_code=400,
            detail="goal text must be non-empty (provide 'text' or 'item')",
        )

    hunt = await orch_hunts.start_hunt(
        user_id=str(user.id),
        goal_text=goal_text,
        session=session,
    )
    # Persist the brief (BuyingBrief shape) when the frontend supplied it.
    if body.item is not None:
        brief = body.model_dump(exclude_none=False)
        # Drop the free-form ``text`` so brief stays close to BuyingBrief shape.
        brief.pop("text", None)
        await Hunt.set_brief(session, hunt.id, brief)
    await session.commit()

    # Echo back the original item if provided; otherwise echo the text so
    # the frontend has something to display while the lifecycle clarifies.
    item_echo = body.item or body.text or ""

    logger.info(
        "create_goal: spawned hunt=%s user=%s goal=%r",
        hunt.id,
        str(user.id),
        goal_text,
    )

    return {
        "ok": True,
        "hunt_id": hunt.id,
        "item": item_echo,
        # Stream-A compat: existing frontend code looks at ``goal_id``.
        "goal_id": hunt.id,
    }


# ---------------------------------------------------------------------------
# POST /api/goals/{goal_id}/clarify — legacy clarify route
#
# New flows use the AgentField pause/resume bridge: the clarifier reasoner
# pauses inside the lifecycle, the user POSTs to /api/approvals/{id} with
# ``{feedback: {budget}}``, and the lifecycle continues. This legacy route
# is preserved so older clients that POST budgets directly still get
# listings — it short-circuits the lifecycle's clarify step by writing
# the budget to the hunt row + returning the cached listings.


@router.post("/goals/{goal_id}/clarify", response_model=ClarifyResponse)
async def submit_clarification(
    goal_id: str,
    payload: ClarifyRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ClarifyResponse:
    """Accept a budget for the given hunt and return discovery listings.

    Persists the budget on the hunt row (if the hunt exists) and dispatches
    discovery. NOTE: this short-circuits the lifecycle's clarifier pause —
    the lifecycle's own pause may still be sitting in the approval queue.
    Production flow should resolve the approval via
    ``POST /api/approvals/{id}`` instead.
    """
    hunt = await Hunt.get(session, goal_id)
    if hunt is not None and hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )
    if hunt is not None and payload.budget is not None:
        await Hunt.update_budget(session, goal_id, float(payload.budget))
        await session.commit()

    # Don't kick off any browser-side discovery from this read path —
    # the streaming hunt lifecycle owns that responsibility now (see
    # ``api/orchestration/hunts.py``). Return whatever's already cached.
    _ = hunt  # silence unused-var lint
    return ClarifyResponse(listings=[])


# ---------------------------------------------------------------------------
# GET /api/goals/{hunt_id}/listings — rich listings shape


@router.get("/goals/{hunt_id}/listings", response_model=list[StreamAListing])
async def get_goal_listings(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StreamAListing]:
    """Return the rich ``StreamAListing[]`` shape for the hunt.

    Source order:
    1. In-process valuations cache (the lifecycle's working set; richest data).
    2. ``listings_cache`` table rows where ``goal_id == hunt_id``.
    3. Fallback to a fresh discovery call.

    Each underlying ``Listing`` is mapped via the adapter's
    ``_to_stream_a_listing`` helper so the frontend contract stays one shape.
    """
    # Ownership check — only the hunt's user can read its listings.
    hunt_owner = await Hunt.get(session, hunt_id)
    if hunt_owner is not None and hunt_owner.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )

    # ---- 1. in-process cache ----
    cached = orch_hunts.get_cached_listings(hunt_id)
    if cached:
        results: list[StreamAListing] = []
        for idx, entry in enumerate(cached):
            try:
                internal = Listing.model_validate(entry["listing"])
            except Exception:  # noqa: BLE001 — defensive
                continue
            results.append(_to_stream_a_listing(internal, idx))
        if results:
            return results

    # ---- 2. listings_cache table ----
    try:
        from sqlalchemy import select

        rows = await session.execute(
            select(ListingCache).where(ListingCache.goal_id == hunt_id)
        )
        cache_rows = list(rows.scalars().all())
    except Exception:  # noqa: BLE001 — DB best-effort
        logger.exception(
            "get_goal_listings: listings_cache read failed hunt=%s", hunt_id
        )
        cache_rows = []

    if cache_rows:
        results = []
        for idx, row in enumerate(cache_rows):
            try:
                internal = Listing.model_validate(
                    {
                        "id": row.listing_id,
                        "title": row.title or "",
                        "price": (row.price_cents or 0) / 100.0,
                        "marketplace": row.marketplace,
                        "url": row.url or "",
                        "description": row.description,
                        # Other enrichment fields aren't carried in
                        # listings_cache; the adapter helper defaults them.
                        **{
                            k: v
                            for k, v in (row.raw_data or {}).items()
                            if k in {"image_url", "seller_name", "location"}
                        },
                    }
                )
            except Exception:  # noqa: BLE001
                continue
            results.append(_to_stream_a_listing(internal, idx))
        if results:
            return results

    # No fallback discovery. Earlier versions of this endpoint
    # fell through to ``integ_discovery.search`` when both the
    # in-process cache and ``listings_cache`` were empty — but the
    # SearchPanel polls this endpoint every 2 seconds while a hunt is
    # discovering, and each empty-cache hit was minting a FRESH
    # Browserbase session to re-run full discovery in parallel with
    # the lifecycle's streaming loop. That explained the "6
    # concurrent sessions appear instantly" symptom: every poll
    # spawned another one. The streaming discovery in
    # ``api/orchestration/hunts.py`` is the SOLE source of truth for
    # populating the cache; this read endpoint must NOT trigger any
    # new browser work.
    return []


# ---------------------------------------------------------------------------
# Legacy helpers preserved for tests / older internal callers.


async def _invoke_clarifier(goal: str) -> str:
    """Forward to the ``goti`` Agent's clarifier reasoner.

    Single-shot mode (no hunt_id) — returns the question text directly.
    """
    body = await invoke_reasoner(
        "ask_clarifying_question", {"goal": goal}, raise_on_error=False
    )
    question = body.get("clarifying_question") if isinstance(body, dict) else None
    if not isinstance(question, str) or not question.strip():
        raise HTTPException(
            status_code=502,
            detail=f"Reasoner returned no clarifying_question (raw={body!r})",
        )
    return question


async def _legacy_create_goal_helper(
    payload: CreateGoalRequest,
    background_tasks: BackgroundTasks,
) -> CreateGoalResponse:
    """Pre-Pass-2 helper — returns the legacy ``{goal_id, clarifying_question}``
    shape. Preserved for tests / older internal callers.
    """
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="goal text must be non-empty")

    goal_id = str(uuid.uuid4())
    clarifying_question = await _invoke_clarifier(payload.text)
    orch_jobs.remember_goal(goal_id, payload.text)
    background_tasks.add_task(write_case, payload.text, clarifying_question)

    return CreateGoalResponse(
        goal_id=goal_id,
        clarifying_question=clarifying_question,
    )
