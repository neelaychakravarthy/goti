"""Jobs routes — DB-backed Postgres + reasoner-driven handlers.

See ``api/orchestration/jobs.py`` for the lifecycle docstring.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import current_user, optional_current_user
from api.contracts import Job, NegotiateResponse
from api.db import AsyncSessionLocal, get_session
from api.integrations import discovery as integ_discovery
from api.models import (
    IntegrationAccountRow,
    Job as JobORM,
    ListingCache,
    MessageThread,
    Notification,
    User,
)
from api.orchestration import jobs as orch_jobs
from api.orchestration.sse import job_event_stream
from api import notifications as notif_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])


# ---------------------------------------------------------------------------
# POST /api/listings/{listing_id}/negotiate


async def _resolve_listing(
    listing_id: str,
    *,
    user_id: str,
    session: AsyncSession,
):
    """Look up a Listing by id.

    Reads from ``listings_cache`` first — the hunt lifecycle populates
    this table for every discovered listing, so the cache miss path is
    rare in production. On miss we fall back to a fresh browser-agent
    discovery call, which requires a logged-in Browserbase context for
    the user (raises if none).
    """
    from sqlalchemy import select

    from api.contracts import Listing
    from api.models import ListingCache

    rows = await session.execute(
        select(ListingCache).where(ListingCache.listing_id == listing_id)
    )
    cached = rows.scalars().first()
    if cached is not None:
        try:
            return Listing.model_validate(
                {
                    "id": cached.listing_id,
                    "title": cached.title or "",
                    "price": (cached.price_cents or 0) / 100.0,
                    "marketplace": cached.marketplace,
                    "url": cached.url or "",
                    "description": cached.description,
                    **{
                        k: v
                        for k, v in (cached.raw_data or {}).items()
                        if k in {"image_url", "seller_name", "location"}
                    },
                }
            )
        except Exception:  # noqa: BLE001 — fall through to fresh discovery
            logger.warning(
                "_resolve_listing: cache row failed validation for %s; "
                "falling back to fresh discovery",
                listing_id,
            )

    candidates = await integ_discovery.search(
        user_id=user_id,
        query="",
        marketplaces=["fb", "nextdoor", "offerup", "craigslist"],
        max_per_source=20,
        session=session,
    )
    for li in candidates:
        if li.id == listing_id:
            return li
    return None


@router.post("/listings/{listing_id}/negotiate", response_model=NegotiateResponse)
async def negotiate(
    listing_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NegotiateResponse:
    """Spawn a negotiation job and return ``{job_id}`` synchronously.

    The negotiator reasoner is fired as a background task — it will call
    ``app.pause()`` internally, which routes through
    ``api/routes/agent_bridge.py`` → ``notifications`` → SSE push. The
    user resolves via ``POST /api/approvals/{approval_request_id}`` and
    the bridge POSTs back to the agent's ``/webhooks/approval``.

    The pre-properization shape (skip-pause path + synchronous draft +
    immediate approval_queue row) has been removed; the bridge now owns
    the approval_queue row's lifecycle (created from the reasoner's
    pause() payload).
    """
    uid = str(user.id)
    listing = await _resolve_listing(listing_id, user_id=uid, session=session)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"unknown listing_id: {listing_id}")

    # Best-effort valuation -> target_price (None on failure).
    target_price: Optional[float] = await orch_jobs.invoke_valuation_for_listing(
        listing, budget=None, user_id=uid
    )

    job = await orch_jobs.spawn_job(
        session,
        listing=listing,
        target_price=target_price,
        user_id=uid,
    )
    await session.commit()

    # Seed BATNA via the coordinator reasoner (best-effort, non-blocking on
    # error since BATNA leverage is enrichment, not load-bearing for round 1).
    await orch_jobs.seed_batna_via_coordinator(
        goal_id=listing_id,  # surrogate; goals aren't persisted
        listings=[listing],
        target_listing_ids=[listing_id],
        target_price=float(target_price) if target_price is not None else 0.0,
        user_id=uid,
    )

    # Fire the negotiator in the background; it will pause internally and
    # the bridge will materialize the approval card + notification.
    orch_jobs.spawn_negotiator_in_background(
        job_id=job.id,
        conversation=[],
        target_price=target_price,
        user_id=uid,
    )

    logger.info(
        "negotiate: spawned job=%s listing=%s target_price=%s (background reasoner)",
        job.id,
        listing_id,
        target_price,
    )
    return NegotiateResponse(job_id=job.id)


# ---------------------------------------------------------------------------
# GET /api/jobs


@router.get("/jobs", response_model=list[Job])
async def list_jobs(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Job]:
    rows = await JobORM.list_for_user(session, str(user.id))
    results: list[Job] = []
    for r in rows:
        composed = await orch_jobs.build_job_response(session, r.id)
        if composed is not None:
            results.append(composed)
    return results


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}


@router.get("/jobs/{job_id}", response_model=Job)
async def get_job(
    job_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Job:
    composed = await orch_jobs.build_job_response(session, job_id)
    if composed is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
    if composed.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="job does not belong to the current user"
        )
    return composed


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/stream — SSE


@router.get("/jobs/{job_id}/stream")
async def stream_job(
    job_id: str,
    user: Optional[User] = Depends(optional_current_user),
) -> StreamingResponse:
    # SSE: EventSource can't set headers, so we accept the token via ``?token=``
    # (handled by ``optional_current_user``). If no token is supplied the
    # stream still serves — the SSE itself doesn't leak per-user state (it
    # only echoes job-id-scoped events).
    _ = user
    # NOTE: the generator opens its own DB session per-iteration; we do NOT
    # pass the dependency-injected session because that would close when
    # this route returns (before the generator yields its first event).
    return StreamingResponse(
        job_event_stream(job_id),
        media_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/draft-next — user-triggered draft kickoff
# ---------------------------------------------------------------------------


@router.post("/jobs/{job_id}/draft-next")
async def draft_next(
    job_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Spawn the negotiator for ``job_id`` in the background.

    Phase D of the ancient-brewing-brooks plan: ``POST /api/hunts/{id}/jobs``
    no longer auto-spawns the negotiator; instead the deal page shows
    a "Start negotiating" button that calls THIS endpoint when the user
    is ready. Idempotent against in-flight lifecycles — calling twice
    just queues a second draft attempt, which the lifecycle handles
    via its own re-entry guards.

    Returns ``{ok, job_id, spawned}``. ``spawned=False`` means the job
    doesn't exist (404) or has no parent — see the body for context.
    """
    job = await JobORM.get(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
    if job.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="job does not belong to the current user"
        )
    if job.status in ("closed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"job is {job.status}; no more drafts expected",
        )

    spawned = await orch_jobs.spawn_job_draft(job_id)
    return {"ok": True, "job_id": job_id, "spawned": spawned}


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/check-replies — user-triggered reply fetch
# ---------------------------------------------------------------------------


async def _resolve_listing_url_marketplace(
    session: AsyncSession, listing_id: str
) -> tuple[str, str]:
    """Look up ``(url, marketplace)`` for a listing from ``listings_cache``.

    Returns ``("", "fb")`` when no cache row matches — the caller treats
    an empty url as "cannot fetch" and raises an actionable 400.
    """
    rows = await session.execute(
        select(ListingCache.url, ListingCache.marketplace)
        .where(ListingCache.listing_id == listing_id)
        .limit(1)
    )
    row = rows.first()
    if row is None:
        return "", "fb"
    url_val = row[0] or ""
    marketplace_val = row[1] or "fb"
    return url_val, marketplace_val


async def _spawn_negotiator_after_reply_safe(
    *,
    job_id: str,
    user_id: str,
) -> None:
    """Spawn the negotiator after a user-triggered reply was persisted.

    Loads the Job + listing + conversation, computes the BATNA context
    for sibling jobs in the same hunt, and invokes
    ``invoke_negotiator_for_draft``. The negotiator pauses internally on
    ``app.pause()`` — the bridge router materializes the approval row +
    notification so the new counter-draft shows up on ``/approve`` and
    ``/deal/[id]``.

    Wrapped in a defensive try/except: a failure here writes an
    ``error`` notification but never crashes the FastAPI worker.
    """
    try:
        async with AsyncSessionLocal() as session:
            job = await JobORM.get(session, job_id)
            if job is None:
                logger.error(
                    "_spawn_negotiator_after_reply_safe: job=%s not found", job_id
                )
                return
            target_price = job.target_price
            hunt_id = job.hunt_id

            messages = await MessageThread.list_for_job(session, job_id)
            conversation = [
                {"role": m.role, "text": m.text} for m in messages
            ]
            batna_context = await orch_jobs.get_batna_context_for_hunt(
                hunt_id=hunt_id, exclude_job_id=job_id, session=session
            )

        await orch_jobs.invoke_negotiator_for_draft(
            job_id=job_id,
            conversation=conversation,
            target_price=target_price,
            user_id=user_id,
            batna_context=batna_context,
        )
    except Exception:  # noqa: BLE001 — surface an error notification, don't crash
        logger.exception(
            "_spawn_negotiator_after_reply_safe: failed job=%s", job_id
        )
        try:
            async with AsyncSessionLocal() as session:
                notif = await Notification.create(
                    session,
                    user_id=user_id,
                    kind="error",
                    title="Check failed",
                    body="Goti couldn't draft a reply — try again in a moment.",
                    target_href=f"/deal/{job_id}",
                    job_id=job_id,
                    payload={"job_id": job_id},
                )
                await session.commit()
                await notif_queue.enqueue(notif.to_event_dict())
        except Exception:  # noqa: BLE001 — never propagate
            logger.exception(
                "_spawn_negotiator_after_reply_safe: error-notif failed job=%s",
                job_id,
            )


@router.post("/jobs/{job_id}/finalize-close")
async def finalize_close(
    job_id: str,
    body: dict,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Finalize a deal close: yes-message + sibling declines + hunt close.

    Phase F of the ancient-brewing-brooks plan. Body shape:
    ``{final_price: float, agreed_text?: str}``.

    Pre-condition: ``Job.ready_to_close`` is True (the Phase E
    classifier reasoner has signalled a natural close-point). Returns
    409 with the reason when the precondition isn't met.

    Behaviour delegated to ``api.orchestration.jobs.finalize_close``:
    persists the yes-message + dispatches via browser-agent, persists +
    dispatches the hardcoded decline template to every sibling Job in
    the same hunt, closes the chosen Job (records ``final_price``),
    closes the parent Hunt, writes a Case to EverOS, and emits a
    ``deal_closed`` notification.
    """
    # Ownership check first — the orchestration helper trusts its
    # caller, so we enforce here.
    job = await JobORM.get(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
    if job.user_id != str(user.id):
        raise HTTPException(
            status_code=403,
            detail="job does not belong to the current user",
        )

    raw_price = body.get("final_price") if isinstance(body, dict) else None
    try:
        final_price = float(raw_price) if raw_price is not None else None
    except (TypeError, ValueError):
        final_price = None
    if final_price is None or final_price <= 0:
        raise HTTPException(
            status_code=400,
            detail="final_price (positive number) is required",
        )

    agreed_text_raw = body.get("agreed_text") if isinstance(body, dict) else None
    agreed_text: Optional[str] = None
    if isinstance(agreed_text_raw, str) and agreed_text_raw.strip():
        agreed_text = agreed_text_raw.strip()

    try:
        result = await orch_jobs.finalize_close(
            job_id=job_id,
            final_price=final_price,
            agreed_text=agreed_text,
        )
    except ValueError as exc:
        # Pre-condition failure (not ready_to_close / job terminal).
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return result


@router.post("/jobs/{job_id}/check-replies")
async def check_replies(
    job_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """User-triggered reply check.

    Runs ONE browser-agent fetch against the user's Browserbase
    context. If a reply is found:

    - Persist each reply to ``message_threads`` (role='seller').
    - Advance the Job back to ``active``.
    - Spawn the negotiator in the background — it drafts a counter and
      pauses for approval (bridge router materializes the approval row
      + notification).

    If no reply, returns ``{found: False, checked_at: ...}`` so the UI
    can surface a "Nothing new yet" state.
    """
    # 1. Auth + ownership check.
    job = await JobORM.get(session, job_id)
    if job is None or job.user_id != str(user.id):
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in ("closed", "cancelled"):
        raise HTTPException(
            status_code=400, detail=f"job is {job.status}; no more replies expected"
        )

    # 2. Look up the listing url + marketplace from listings_cache.
    listing_url, marketplace = await _resolve_listing_url_marketplace(
        session, job.listing_id
    )
    if not listing_url:
        raise HTTPException(
            status_code=400,
            detail="listing url not available; cannot check replies",
        )

    # 3. Resolve user's Browserbase context id.
    ia_rows = await IntegrationAccountRow.list_active_for_user(session, str(user.id))
    context_id: Optional[str] = None
    for row in ia_rows:
        if (
            row.provider == ("nextdoor" if marketplace == "nextdoor" else "fb")
            and row.browserbase_context_id
        ):
            context_id = row.browserbase_context_id
            break
    if context_id is None:
        # Fall back to any active row's context (single context covers all
        # marketplaces the user logged into inside the Live View tab).
        for row in ia_rows:
            if row.browserbase_context_id:
                context_id = row.browserbase_context_id
                break
    if context_id is None:
        raise HTTPException(
            status_code=412,
            detail="no active marketplace links; link via onboarding",
        )

    # 4. Run the agent — ONE fetch. Use the last message's sent_at as since_ts.
    last_message = await MessageThread.last_for_job(session, job_id)
    since_ts = (
        last_message.sent_at.timestamp() if last_message and last_message.sent_at else 0.0
    )

    from api.integrations.browser_agent import actions as agent_actions
    from api.orchestration import tasks as _task_registry

    # Phase L — surface "Checking for seller replies" in the chat
    # while the browser fetch runs (1-2s typical).
    task_id = None
    try:
        task_id = _task_registry.start_task(
            kind="check_replies",
            hunt_id=job.hunt_id,
            job_id=str(job.id),
            label="Checking for seller replies",
            user_id=str(user.id),
        )
    except Exception:  # noqa: BLE001
        task_id = None

    try:
        replies = await agent_actions.fetch_replies(
            context_id=context_id,
            listing_url=listing_url,
            listing_id=job.listing_id,
            marketplace=marketplace,
            since_ts=since_ts,
            hunt_id=job.hunt_id,
            job_id=str(job.id),
        )
    except Exception as exc:  # noqa: BLE001 — never crash the worker
        logger.exception(
            "check_replies: fetch_replies raised job=%s", job_id
        )
        replies = []
        if task_id:
            _task_registry.finish_task(
                task_id, status="errored", summary=str(exc)
            )
            task_id = None

    checked_at = datetime.now(timezone.utc).isoformat()

    if not replies:
        if task_id:
            _task_registry.finish_task(
                task_id,
                status="completed",
                summary="No new replies yet",
            )
        return {"found": False, "checked_at": checked_at}
    if task_id:
        _task_registry.finish_task(
            task_id,
            status="completed",
            summary=f"Got {len(replies)} seller message(s)",
        )

    # 5. Persist each reply + advance job state.
    persisted_count = 0
    last_reply_text = ""
    for reply in replies:
        text = getattr(reply, "text", None)
        if text is None and isinstance(reply, dict):
            text = reply.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        await MessageThread.append(
            session, job_id=job_id, role="seller", text=text.strip()
        )
        last_reply_text = text.strip()
        persisted_count += 1

    if persisted_count == 0:
        # Got replies but none had usable text — same as no reply.
        return {"found": False, "checked_at": checked_at}

    await JobORM.advance_status(
        session, job_id, "active", bump_last_message_at=True
    )
    await session.commit()

    # User-facing seller_replied notification.
    try:
        notif = await Notification.create(
            session,
            user_id=str(user.id),
            kind="seller_replied",
            title="Seller replied",
            body=(last_reply_text[:160] if last_reply_text else "New seller message."),
            target_href=f"/deal/{job_id}",
            job_id=job_id,
            payload={"job_id": job_id, "reply_text": last_reply_text},
        )
        await session.commit()
        await notif_queue.enqueue(notif.to_event_dict())
    except Exception:  # noqa: BLE001 — non-fatal
        logger.exception(
            "check_replies: seller_replied notif failed job=%s", job_id
        )

    # 6. Spawn the classifier first (cheap LLM call) so the readiness
    # signal is up-to-date by the time the user reads the counter-draft.
    # Phase E of the ancient-brewing-brooks plan.
    orch_jobs.spawn_classifier_in_background(job_id)

    # 7. Spawn the negotiator in the background to draft the counter.
    asyncio.create_task(
        _spawn_negotiator_after_reply_safe(
            job_id=job_id,
            user_id=str(user.id),
        )
    )

    return {
        "found": True,
        "reply_count": persisted_count,
        "checked_at": checked_at,
    }
