"""Hunts routes — long-running hunt lifecycle inspection.

Endpoints:

- ``GET /api/hunts`` — list hunts for the current authenticated user.
- ``GET /api/hunts/active`` — the user's most-recently-touched
  non-terminal hunt (or 204 No Content if none).
- ``GET /api/hunts/{hunt_id}`` — single hunt's current state (must
  belong to the current user). Response includes derived counts
  (``candidates_count``, ``open_negotiations_count``,
  ``pending_hitl_count``, ``last_activity_at``) so a single round-trip
  populates the persistent status bar.
- ``GET /api/hunts/{hunt_id}/activity`` — list of per-step
  browser-agent activity events (thinking + next_goal + action_summary)
  ordered oldest-first. Powers the live reasoning timeline in the hunt
  detail UI; the frontend polls this every few seconds.
- ``POST /api/hunts/{hunt_id}/jobs`` — start a negotiation on a
  surfaced candidate. Body: ``{listing_id, target_price?}``. Creates
  the ``Job`` row, flips the hunt to ``negotiating`` if it was
  ``awaiting_picks``, and spawns ``run_job_lifecycle_safe`` in the
  background. The user can fire this any time during streaming
  discovery — discovery keeps running in parallel.

The hunt itself is created via ``POST /api/goals`` (see
``api/routes/goals.py``); the lifecycle coroutine runs in the background
and mutates the hunt's ``status`` column as it advances. These read
endpoints surface that state for the frontend.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import current_user
from api.db import get_session
from api.models import (
    ApprovalQueueItem,
    Hunt,
    HuntActivityEvent,
    Job,
    ListingCache,
    MessageThread,
    Notification,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hunts", tags=["hunts"])


# Statuses considered "open" for negotiation counting.
_OPEN_JOB_STATUSES = (
    "active",
    "awaiting_seller_reply",
    "awaiting_user_approval",
)

# Hunt-level pending HITL: scoped to approval_request_ids that match
# ``hunt-<id>-*`` (clarifier/picker pauses). Job-bound pending HITL is
# counted separately by joining approval_queue.job_id to this hunt's jobs.
_HUNT_TERMINAL_STATUSES = ("closed", "error")


def _serialize_basic(hunt: Hunt) -> dict:
    return {
        "id": hunt.id,
        "user_id": hunt.user_id,
        "goal_text": hunt.goal_text,
        "brief": hunt.brief,
        "budget": hunt.budget,
        "status": hunt.status,
        "lifecycle_phase": hunt.lifecycle_phase,
        "created_at": hunt.created_at.isoformat() if hunt.created_at else None,
        "updated_at": hunt.updated_at.isoformat() if hunt.updated_at else None,
    }


async def _compute_hunt_counts(
    session: AsyncSession, hunt: Hunt
) -> dict:
    """Compute the derived per-hunt counts surfaced in ``GET /api/hunts/{id}``.

    Counts:
    - ``candidates_count`` — listings_cache rows for this hunt's goal_id.
    - ``open_negotiations_count`` — jobs in non-terminal status under this hunt.
    - ``awaiting_reply_count`` — jobs in ``awaiting_seller_reply`` status
      under this hunt (lets the HuntStatusBar show "N awaiting reply
      (click to check)").
    - ``pending_hitl_count`` — undecided approval_queue rows
      (job-scoped + hunt-scoped via ``hunt-<id>-*`` request ids).
    - ``last_activity_at`` — most recent notification timestamp for this hunt.
    - ``tab_badges`` — Phase T: per-job unresolved-items count
      (pending approvals + ready-to-close + newer-seller-reply).
    """
    hunt_id = hunt.id

    # candidates_count — listings_cache rows keyed by goal_id == hunt_id.
    try:
        import uuid as _uuid_mod
        candidates_count = await session.scalar(
            select(func.count())
            .select_from(ListingCache)
            .where(ListingCache.goal_id == _uuid_mod.UUID(hunt_id))
        ) or 0
    except Exception:  # noqa: BLE001
        logger.exception("_compute_hunt_counts: candidates count failed hunt=%s", hunt_id)
        candidates_count = 0

    # open_negotiations_count — Jobs for this hunt in a non-terminal status.
    try:
        open_negotiations_count = await session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.hunt_id == hunt_id,
                Job.status.in_(_OPEN_JOB_STATUSES),
            )
        ) or 0
    except Exception:  # noqa: BLE001
        logger.exception(
            "_compute_hunt_counts: open negotiations count failed hunt=%s",
            hunt_id,
        )
        open_negotiations_count = 0

    # awaiting_reply_count — Jobs sitting in awaiting_seller_reply waiting
    # for the user to click "Check for reply". Surfaced separately so the
    # HuntStatusBar can show a distinct color + CTA.
    try:
        awaiting_reply_count = await session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.hunt_id == hunt_id,
                Job.status == "awaiting_seller_reply",
            )
        ) or 0
    except Exception:  # noqa: BLE001
        logger.exception(
            "_compute_hunt_counts: awaiting_reply count failed hunt=%s",
            hunt_id,
        )
        awaiting_reply_count = 0

    # pending_hitl_count — sum of:
    #   (a) job-scoped approvals where the job belongs to this hunt and
    #       decision IS NULL.
    #   (b) hunt-scoped approvals (approval_request_id starting with
    #       ``hunt-<id>-``) with decision IS NULL.
    pending_hitl_count = 0
    try:
        job_scoped = await session.scalar(
            select(func.count())
            .select_from(ApprovalQueueItem)
            .join(Job, ApprovalQueueItem.job_id == Job.id)
            .where(
                Job.hunt_id == hunt_id,
                ApprovalQueueItem.decision.is_(None),
            )
        ) or 0
        hunt_prefix = f"hunt-{hunt_id}-"
        hunt_scoped = await session.scalar(
            select(func.count())
            .select_from(ApprovalQueueItem)
            .where(
                ApprovalQueueItem.approval_request_id.like(f"{hunt_prefix}%"),
                ApprovalQueueItem.decision.is_(None),
            )
        ) or 0
        pending_hitl_count = int(job_scoped) + int(hunt_scoped)
    except Exception:  # noqa: BLE001
        logger.exception(
            "_compute_hunt_counts: pending HITL count failed hunt=%s", hunt_id
        )

    # last_activity_at — most recent notification for this hunt.
    last_activity_at: Optional[str] = None
    try:
        last_dt = await session.scalar(
            select(func.max(Notification.created_at)).where(
                Notification.hunt_id == hunt_id
            )
        )
        if last_dt is not None:
            last_activity_at = last_dt.isoformat()
    except Exception:  # noqa: BLE001
        logger.exception(
            "_compute_hunt_counts: last_activity_at failed hunt=%s", hunt_id
        )

    # tab_badges — Phase T: per-job badge count keyed by job_id.
    tab_badges: dict[str, int] = {}
    try:
        tab_badges = await _compute_tab_badges(session, hunt_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "_compute_hunt_counts: tab_badges failed hunt=%s", hunt_id
        )

    return {
        "candidates_count": int(candidates_count),
        "open_negotiations_count": int(open_negotiations_count),
        "awaiting_reply_count": int(awaiting_reply_count),
        "pending_hitl_count": int(pending_hitl_count),
        "last_activity_at": last_activity_at,
        "tab_badges": tab_badges,
    }


async def _compute_tab_badges(
    session: AsyncSession, hunt_id: str
) -> dict[str, int]:
    """Compute per-job unresolved-items counts for the negotiation tab strip.

    For each non-terminal job under this hunt:
    - +1 per undecided ``approval_queue`` row bound to the job
    - +1 if ``Job.ready_to_close`` is True
    - +1 if the most-recent ``seller``-role message is newer than the
      most-recent ``buyer_agent``-role message (user has an unread
      seller reply on this thread).

    Returns ``{job_id: count}`` for jobs whose count > 0. Job rows
    with zero unresolved items are omitted so the wire payload stays
    small.
    """
    jobs_q = await session.execute(
        select(Job).where(
            Job.hunt_id == hunt_id,
            Job.status.notin_(("closed", "cancelled")),
        )
    )
    jobs = list(jobs_q.scalars().all())
    if not jobs:
        return {}

    job_ids = [j.id for j in jobs]

    # Pending approvals per job.
    pending_by_job: dict[str, int] = {jid: 0 for jid in job_ids}
    try:
        from sqlalchemy import func as _func
        approval_rows = await session.execute(
            select(ApprovalQueueItem.job_id, _func.count())
            .where(
                ApprovalQueueItem.job_id.in_(job_ids),
                ApprovalQueueItem.decision.is_(None),
            )
            .group_by(ApprovalQueueItem.job_id)
        )
        for row in approval_rows.all():
            jid, cnt = row[0], row[1]
            if isinstance(jid, str):
                pending_by_job[jid] = int(cnt or 0)
    except Exception:  # noqa: BLE001
        logger.exception(
            "_compute_tab_badges: pending approvals lookup failed hunt=%s",
            hunt_id,
        )

    # Newer-seller-than-buyer: pull the most-recent message of each
    # role per job. SQLite + UUID columns make a window function path
    # awkward; the simpler shape is a single pass over MessageThread.
    seller_newer_by_job: dict[str, bool] = {jid: False for jid in job_ids}
    try:
        from sqlalchemy import select as _select
        msg_rows = await session.execute(
            _select(
                MessageThread.job_id,
                MessageThread.role,
                MessageThread.sent_at,
            ).where(MessageThread.job_id.in_(job_ids))
        )
        last_seller: dict = {}
        last_buyer: dict = {}
        for row in msg_rows.all():
            jid, role, sent_at = row[0], row[1], row[2]
            if not isinstance(jid, str) or sent_at is None:
                continue
            if role == "seller":
                if jid not in last_seller or sent_at > last_seller[jid]:
                    last_seller[jid] = sent_at
            elif role == "buyer_agent":
                if jid not in last_buyer or sent_at > last_buyer[jid]:
                    last_buyer[jid] = sent_at
        for jid in job_ids:
            seller_ts = last_seller.get(jid)
            buyer_ts = last_buyer.get(jid)
            if seller_ts is not None and (
                buyer_ts is None or seller_ts > buyer_ts
            ):
                seller_newer_by_job[jid] = True
    except Exception:  # noqa: BLE001
        logger.exception(
            "_compute_tab_badges: seller/buyer message lookup failed hunt=%s",
            hunt_id,
        )

    out: dict[str, int] = {}
    for j in jobs:
        c = pending_by_job.get(j.id, 0)
        if bool(j.ready_to_close):
            c += 1
        if seller_newer_by_job.get(j.id, False):
            c += 1
        if c > 0:
            out[j.id] = c
    return out


async def _serialize_with_counts(
    session: AsyncSession, hunt: Hunt
) -> dict:
    out = _serialize_basic(hunt)
    out.update(await _compute_hunt_counts(session, hunt))
    return out


@router.get("")
async def list_hunts(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = await Hunt.list_for_user(session, str(user.id))
    return [_serialize_basic(r) for r in rows]


@router.get("/active")
async def get_active_hunt(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Return the user's most-recently-touched non-terminal hunt.

    "Most-recently-touched" = ``ORDER BY updated_at DESC``. Filters out
    ``closed`` / ``error`` hunts. Returns ``204 No Content`` (with an
    empty body) when no active hunt exists — the persistent status bar
    on the frontend hides itself in that case.

    Response carries the same derived counts as ``GET /api/hunts/{id}``
    so a single fetch populates the bar without a follow-up call.
    """
    result = await session.execute(
        select(Hunt)
        .where(
            Hunt.user_id == str(user.id),
            Hunt.status.notin_(_HUNT_TERMINAL_STATUSES),
        )
        .order_by(Hunt.updated_at.desc())
        .limit(1)
    )
    hunt = result.scalar_one_or_none()
    if hunt is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    from fastapi.responses import JSONResponse

    return JSONResponse(await _serialize_with_counts(session, hunt))


@router.get("/{hunt_id}")
async def get_hunt(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )
    return await _serialize_with_counts(session, hunt)


@router.get("/{hunt_id}/running-tasks")
async def get_hunt_running_tasks(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the currently-running async background tasks for a hunt.

    Phase L — powers the top-of-chat "Running" strip + the chat
    timeline's inline status pills. Tasks are in-memory (single process)
    and disappear when they finish.
    """
    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )

    from api.orchestration import tasks as task_registry

    return {"tasks": task_registry.list_running_for_hunt(hunt_id)}


@router.get("/{hunt_id}/activity")
async def get_hunt_activity(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the per-step browser-agent reasoning timeline for a hunt.

    Oldest-first so a polling client can append-only. The UI polls this
    every few seconds while a hunt is active; once the hunt is closed
    the list stops growing.
    """
    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )

    rows = await HuntActivityEvent.list_for_hunt(session, hunt_id)
    return {"events": [row.to_dict() for row in rows]}


@router.get("/{hunt_id}/listings")
async def get_hunt_listings(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the hunt's cached listings, annotated with ``job_id`` if accepted.

    Powers the Listings tab's split between "Discovered" (no
    ``job_id``) and "Accepted" (``job_id`` present) — see Phase C of the
    ancient-brewing-brooks plan. Each entry mirrors the discovery-time
    ``ListingCache`` row's ``raw_data`` plus a ``job_id`` key (or
    ``null`` when no Job exists for that listing under this hunt).
    """
    import uuid as _uuid_mod

    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )

    # 1. Pull listings_cache rows scoped to this hunt's goal_id.
    try:
        lc_result = await session.execute(
            select(ListingCache).where(
                ListingCache.goal_id == _uuid_mod.UUID(hunt_id)
            )
        )
        listing_rows = list(lc_result.scalars().all())
    except Exception:  # noqa: BLE001 — DB best-effort
        logger.exception(
            "get_hunt_listings: ListingCache lookup failed hunt=%s",
            hunt_id,
        )
        listing_rows = []

    # 2. Pull every Job under this hunt and key by listing_id so we can
    # annotate. Includes terminal jobs (closed / cancelled) — the UI may
    # want to show "you negotiated this one and closed it" rather than
    # offering re-negotiation on a closed listing.
    try:
        job_result = await session.execute(
            select(Job).where(Job.hunt_id == hunt_id)
        )
        jobs_by_listing: dict[str, Job] = {}
        for row in job_result.scalars().all():
            # If multiple jobs exist for the same listing (legacy data),
            # the most recently created wins — Job.list_for_user returns
            # newest-first but this raw query doesn't. Order by created_at
            # explicitly so the annotation is deterministic.
            existing = jobs_by_listing.get(row.listing_id)
            if existing is None or (
                row.created_at is not None
                and existing.created_at is not None
                and row.created_at > existing.created_at
            ):
                jobs_by_listing[row.listing_id] = row
    except Exception:  # noqa: BLE001 — DB best-effort
        logger.exception(
            "get_hunt_listings: Job lookup failed hunt=%s", hunt_id
        )
        jobs_by_listing = {}

    listings: list[dict] = []
    for row in listing_rows:
        raw = dict(row.raw_data or {})
        raw.setdefault("id", row.listing_id)
        raw.setdefault("marketplace", row.marketplace)
        raw.setdefault("title", row.title or "")
        raw.setdefault(
            "price",
            (row.price_cents / 100.0) if row.price_cents is not None else 0.0,
        )
        raw.setdefault("url", row.url or "")
        job = jobs_by_listing.get(row.listing_id)
        listings.append(
            {
                **raw,
                "job_id": job.id if job is not None else None,
                "job_status": job.status if job is not None else None,
            }
        )

    return {"hunt_id": hunt_id, "listings": listings}


@router.delete("/{hunt_id}")
async def delete_hunt(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Completely remove a hunt and everything attached to it.

    Order of operations (each step best-effort, full transaction
    rolled back on a failure):

    1. Cancel any registered in-flight tasks for this hunt (hunt
       lifecycle + every job lifecycle). ``run_action``'s try/finally
       runs ``bb.end_session`` so Browserbase sessions still in flight
       are released cleanly when the task raises ``CancelledError``.
    2. Flip ``Hunt.status`` to ``closed`` so any task missed by the
       cancellation (race window) will exit on its next status check
       instead of continuing to mutate DB state.
    3. Delete child rows in dependency order — message_threads +
       approval_queue (job-scoped), jobs (hunt-scoped), notifications
       (hunt-scoped), listings_cache (goal_id == hunt_id),
       hunt_activity_events (cascades on the hunts FK).
    4. Delete the ``Hunt`` row itself.

    Caller must own the hunt — 403 otherwise.
    """
    import uuid as _uuid_mod
    from sqlalchemy import delete as _delete

    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )

    # ---- Step 1: cancel in-flight tasks ----
    from api.orchestration.hunts import (
        cancel_hunt_tasks_async,
        _HUNT_LISTINGS,
    )

    _HUNT_LISTINGS.pop(hunt_id, None)

    # ---- Step 2: flip status so any racing task exits cleanly ----
    hunt.status = "closed"
    hunt.lifecycle_phase = "closed"
    await session.flush()

    # Block until cancelled tasks have actually finished their
    # ``finally`` blocks so Browserbase sessions are released
    # upstream BEFORE we drop the DB rows referenced by those tasks.
    cancelled = await cancel_hunt_tasks_async(hunt_id)

    # ---- Step 3: cascade child rows ----
    job_ids_q = select(Job.id).where(Job.hunt_id == hunt_id)
    job_ids = [row[0] for row in (await session.execute(job_ids_q)).all()]

    if job_ids:
        await session.execute(
            _delete(MessageThread).where(MessageThread.job_id.in_(job_ids))
        )
        await session.execute(
            _delete(ApprovalQueueItem).where(
                ApprovalQueueItem.job_id.in_(job_ids)
            )
        )
        await session.execute(_delete(Job).where(Job.id.in_(job_ids)))

    await session.execute(
        _delete(Notification).where(Notification.hunt_id == hunt_id)
    )
    # ``listings_cache.goal_id`` is a UUID column — coerce the string
    # hunt_id like the rest of the codebase does.
    await session.execute(
        _delete(ListingCache).where(
            ListingCache.goal_id == _uuid_mod.UUID(hunt_id)
        )
    )
    # hunt_activity_events has ON DELETE CASCADE on its hunt_id FK, so
    # deleting the Hunt row below would clean it up — but be explicit
    # for backends without enforced FK cascade (SQLite).
    await session.execute(
        _delete(HuntActivityEvent).where(HuntActivityEvent.hunt_id == hunt_id)
    )

    # ---- Step 4: delete the hunt itself ----
    await session.delete(hunt)
    await session.commit()

    return {
        "ok": True,
        "hunt_id": hunt_id,
        "tasks_cancelled": cancelled,
        "jobs_deleted": len(job_ids),
    }


# ---------------------------------------------------------------------------
# Pause / resume / stop — lifecycle controls
#
# These three endpoints let the user manage a hunt's activity without
# deleting it. ``stop`` and ``pause`` both cancel in-flight tasks (so
# Browserbase sessions get released cleanly via run_action's
# try/finally); they differ only in the terminal status and whether
# the hunt can be resumed. ``resume`` re-spawns the lifecycle
# coroutine; the streaming discovery loop rehydrates ``seen_ids``
# from listings_cache so it picks up where it left off rather than
# re-finding the same listings.


@router.post("/{hunt_id}/pause")
async def pause_hunt(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cancel in-flight tasks + set status=paused.

    The streaming discovery loop checks ``hunt.status`` between
    iterations and exits cleanly when it sees ``paused``; any
    Browserbase session active inside a ``run_action`` call gets
    released via the CancelledError path. The hunt's listings_cache +
    activity events are preserved so a later ``/resume`` picks up.
    """
    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )
    if hunt.status in ("closed", "error"):
        raise HTTPException(
            status_code=409,
            detail=f"hunt is {hunt.status}; cannot pause a terminal hunt",
        )

    from api.orchestration.hunts import cancel_hunt_tasks_async

    # Flip status FIRST so any task that races our cancel sees it in
    # the DB on its next check and exits cleanly via that path too.
    hunt.status = "paused"
    # Don't touch lifecycle_phase — resume reads it to know which phase
    # to re-enter.
    await session.commit()
    # Block until cancelled tasks have actually run their finally
    # blocks (browser-use Agent.close + browser_session.kill +
    # bb.end_session). With ``asyncio.shield`` inside run_action's
    # finally, this guarantees Browserbase sessions are released
    # upstream before the route responds.
    cancelled = await cancel_hunt_tasks_async(hunt_id)
    return {
        "ok": True,
        "hunt_id": hunt_id,
        "status": "paused",
        "tasks_cancelled": cancelled,
    }


@router.post("/{hunt_id}/resume")
async def resume_hunt(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Re-spawn the lifecycle coroutine for a paused or errored hunt.

    Reads ``lifecycle_phase`` to determine where to pick up:
      - ``clarifying`` → re-invokes the clarifier (the budget question
        may re-surface as a fresh notification).
      - ``discovering`` / ``valuing`` / ``picking`` → restarts streaming
        discovery, which rehydrates ``seen_ids`` from listings_cache so
        it doesn't re-find the same listings.
      - ``negotiating`` → re-spawns per-job coroutines for any
        non-terminal jobs (existing resumption-on-restart branch in
        ``run_hunt_lifecycle``).
    """
    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )
    if hunt.status not in ("paused", "error"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"hunt is {hunt.status}; only paused or errored hunts can "
                "be resumed"
            ),
        )

    # Restore the prior in-flight status based on lifecycle_phase. The
    # streaming discovery loop and per-job coroutines treat
    # ``discovering`` / ``negotiating`` as live; ``paused`` would be an
    # immediate exit signal.
    if hunt.lifecycle_phase in ("clarifying", None):
        hunt.status = "awaiting_clarification"
    elif hunt.lifecycle_phase in ("discovering", "valuing"):
        hunt.status = "discovering"
    elif hunt.lifecycle_phase in ("picking",):
        hunt.status = "awaiting_picks"
    elif hunt.lifecycle_phase in ("negotiating",):
        hunt.status = "negotiating"
    else:
        # Fallback — re-enter discovery and let the loop figure out
        # which marketplaces still need iteration via listings_cache.
        hunt.status = "discovering"
        hunt.lifecycle_phase = "discovering"
    await session.commit()

    import asyncio
    from api.orchestration.hunts import (
        _run_hunt_lifecycle_safe,
        register_hunt_task,
    )

    task = asyncio.create_task(_run_hunt_lifecycle_safe(hunt_id))
    register_hunt_task(hunt_id, task)

    return {"ok": True, "hunt_id": hunt_id, "status": hunt.status}


@router.post("/{hunt_id}/stop")
async def stop_hunt(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cancel in-flight tasks + mark hunt closed. Data is preserved.

    Same as Delete but doesn't drop any rows — useful when the user
    wants to keep the discovered candidates / conversation history
    around for reference but is done actively pursuing the hunt.
    """
    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )

    from api.orchestration.hunts import (
        cancel_hunt_tasks_async,
        _HUNT_LISTINGS,
    )

    _HUNT_LISTINGS.pop(hunt_id, None)
    # Same flip-status-first pattern as pause: tasks racing our cancel
    # will see ``closed`` on their next status check and bail.
    hunt.status = "closed"
    hunt.lifecycle_phase = "closed"
    await session.commit()
    cancelled = await cancel_hunt_tasks_async(hunt_id)
    return {
        "ok": True,
        "hunt_id": hunt_id,
        "status": "closed",
        "tasks_cancelled": cancelled,
    }


@router.post("/{hunt_id}/jobs", status_code=201)
async def start_negotiation(
    hunt_id: str,
    body: dict,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Spawn a negotiation Job for ``listing_id`` under ``hunt_id``.

    Body: ``{listing_id: str, target_price?: float}``. The hunt
    lifecycle no longer waits for a global "picker pause" — instead
    every surfaced candidate is fair game and the user calls this
    endpoint whenever they want to dispatch a job. Streaming discovery
    keeps going in parallel; multiple jobs can be in flight at once.
    """
    listing_id = body.get("listing_id") if isinstance(body, dict) else None
    if not isinstance(listing_id, str) or not listing_id.strip():
        raise HTTPException(status_code=400, detail="listing_id is required")
    target_price_raw = body.get("target_price") if isinstance(body, dict) else None
    target_price: float | None
    try:
        target_price = float(target_price_raw) if target_price_raw is not None else None
    except (TypeError, ValueError):
        target_price = None
    # If the caller didn't supply one, derive a sensible opening target
    # below from the listing's asking price so the deal page renders
    # real numbers instead of $0 placeholders. The Job row carries
    # ``target_price`` and the adapter that builds the next-move panel
    # divides everything from it.

    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )

    # The listing must already be in listings_cache for this hunt —
    # streaming discovery persists every candidate as it surfaces, so
    # this is just a sanity check that the user is acting on a real
    # one.
    import uuid as _uuid_mod
    from sqlalchemy import select as _select
    res = await session.execute(
        _select(ListingCache).where(
            ListingCache.goal_id == _uuid_mod.UUID(hunt_id),
            ListingCache.listing_id == listing_id,
        )
    )
    listing_row = res.scalars().first()
    if listing_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"listing_id {listing_id!r} not surfaced for this hunt",
        )

    # Don't double-spawn if a Job already exists for this listing under
    # this hunt. Returning the existing job_id keeps the caller idempotent.
    existing_res = await session.execute(
        _select(Job).where(
            Job.hunt_id == hunt_id,
            Job.listing_id == listing_id,
        )
    )
    existing_job = existing_res.scalars().first()
    if existing_job is not None:
        return {"job_id": str(existing_job.id), "created": False}

    # Derive an opening target from 85% of the listing's asking price
    # when the caller didn't provide one. Anchors the price ladder on
    # the deal page (Goti recommends / Your max / etc.).
    if target_price is None:
        asking = None
        if isinstance(listing_row.raw_data, dict):
            asking = listing_row.raw_data.get("price")
        if asking is None and listing_row.price_cents is not None:
            asking = listing_row.price_cents / 100.0
        if isinstance(asking, (int, float)) and asking > 0:
            target_price = round(float(asking) * 0.85, 2)

    job = await Job.create(
        session,
        user_id=str(user.id),
        listing_id=listing_id,
        hunt_id=hunt_id,
        status="active",
        target_price=target_price,
    )

    # Flip the hunt to ``negotiating`` so the UI can switch surfaces.
    # Streaming discovery doesn't care about status (it only watches
    # for ``closed`` / ``error``) — it'll keep finding new candidates
    # alongside the in-flight negotiation.
    if hunt.status in ("awaiting_picks", "discovering"):
        hunt.status = "negotiating"
        hunt.lifecycle_phase = "negotiating"
    await session.commit()

    # NB (Phase D of the ancient-brewing-brooks plan): we do NOT spawn
    # ``run_job_lifecycle_safe`` here anymore. The Job row is created
    # ready-to-negotiate, but the negotiator stays dormant until the
    # user explicitly clicks "Start negotiating" on the deal page —
    # which calls ``POST /api/jobs/{job_id}/draft-next`` (see
    # ``api/routes/jobs.py``). Decoupling the lifecycle this way avoids
    # burning LLM tokens on a draft the user might never look at.

    return {"job_id": str(job.id), "created": True}
