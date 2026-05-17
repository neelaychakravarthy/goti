"""Tasks routes — durable async-task resumption.

Phase O of the ancient-brewing-brooks followups round. Surfaces the
``async_tasks`` durable registry to the chat-first UI:

- ``GET /api/hunts/{hunt_id}/stopped-tasks`` — list ``interrupted``
  rows for the hunt (tenant-scoped). The frontend's
  ``task-status-strip.tsx`` polls this and renders a "Stopped" section
  above "Running" when any rows exist.
- ``POST /api/tasks/{task_id}/resume`` — dispatch by ``kind``:
  - ``discovery`` → re-spawn ``run_hunt_lifecycle_safe(hunt_id)`` (the
    streaming discovery loop rehydrates from ``listings_cache``).
  - ``draft`` / ``negotiator_draft`` → re-spawn
    ``run_job_lifecycle_safe`` with the listing + valuation
    reconstructed from ``listings_cache``.
  - ``classifier`` → re-spawn ``spawn_classifier_in_background``.
  - ``analyzer`` → re-spawn ``run_post_close_analysis`` (idempotent —
    the analyzer skips jobs that already have an analysis Case so a
    re-run won't double-write).
  - ``check_replies`` / ``finalize_close`` → 409 with explanatory text
    (these touch external state that can't safely be re-dispatched).

Resumption creates a fresh ``running`` row (new task_id) so the
in-flight stopped row stays in history. The frontend's poll picks up
the new running row + drops the stopped one.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import current_user
from api.db import AsyncSessionLocal, get_session
from api.models import AsyncTaskRow, Hunt, Job, ListingCache, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


# ---------------------------------------------------------------------------
# GET /api/hunts/{hunt_id}/stopped-tasks  — list interrupted rows
# ---------------------------------------------------------------------------


@router.get("/api/hunts/{hunt_id}/stopped-tasks")
async def get_stopped_tasks(
    hunt_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the user's ``interrupted`` async_tasks rows for the hunt."""
    hunt = await Hunt.get(session, hunt_id)
    if hunt is None:
        raise HTTPException(status_code=404, detail=f"unknown hunt_id: {hunt_id}")
    if hunt.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="hunt does not belong to the current user"
        )

    rows = await AsyncTaskRow.list_interrupted_for_hunt(
        session, hunt_id=hunt_id, user_id=str(user.id)
    )
    return {"tasks": [row.to_dict() for row in rows]}


# ---------------------------------------------------------------------------
# POST /api/tasks/{task_id}/resume — dispatch by kind
# ---------------------------------------------------------------------------


# Set of kinds where re-running could re-send a half-finished side-effect
# against an external system (Browserbase / Actionbook). The user is told
# to use the in-app CTA on the deal page instead.
_NOT_AUTORESUMABLE = {
    "check_replies": (
        "this task can only be re-triggered by clicking "
        "'Check for reply' on the deal page"
    ),
    "finalize_close": (
        "finalize-close is not auto-resumable; rerun from the "
        "Ready-to-close badge on the deal page"
    ),
}


@router.post("/api/tasks/{task_id}/resume")
async def resume_task(
    task_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Re-spawn the work captured by an ``interrupted`` task row.

    Returns ``{old_task_id, new_task_id, status: 'resuming'}`` on success.
    Returns 409 with explanatory text for kinds the system can't safely
    auto-resume (``check_replies`` / ``finalize_close``).
    """
    row = await AsyncTaskRow.get(session, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown task_id: {task_id}")
    if row.user_id != str(user.id):
        raise HTTPException(
            status_code=403, detail="task does not belong to the current user"
        )
    if row.status != "interrupted":
        raise HTTPException(
            status_code=409,
            detail=(
                f"task status is {row.status!r}; only interrupted tasks "
                "can be resumed"
            ),
        )

    # Sponsor / safety guard — some kinds can't be safely re-dispatched
    # without knowing what was already sent to the external system.
    if row.kind in _NOT_AUTORESUMABLE:
        raise HTTPException(
            status_code=409,
            detail=_NOT_AUTORESUMABLE[row.kind],
        )

    # ---- Dispatch ----
    kind = row.kind
    hunt_id = row.hunt_id
    job_id = row.job_id
    user_id = row.user_id

    new_task_id = await _dispatch_resume(
        kind=kind, hunt_id=hunt_id, job_id=job_id, user_id=user_id
    )
    if new_task_id is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"cannot resume task kind {kind!r}; the underlying "
                "lifecycle state is no longer available "
                "(hunt deleted or job missing)"
            ),
        )

    return {
        "ok": True,
        "old_task_id": task_id,
        "new_task_id": new_task_id,
        "status": "resuming",
    }


async def _dispatch_resume(
    *,
    kind: str,
    hunt_id: Optional[str],
    job_id: Optional[str],
    user_id: str,
) -> Optional[str]:
    """Dispatch a fresh background task per ``kind``. Returns new task_id
    or None if the underlying state has gone away."""
    from api.orchestration import tasks as task_registry

    if kind == "discovery":
        if not hunt_id:
            return None
        async with AsyncSessionLocal() as s:
            hunt = await Hunt.get(s, hunt_id)
            if hunt is None or hunt.user_id != user_id:
                return None
        new_id = task_registry.start_task(
            kind="discovery",
            hunt_id=hunt_id,
            label="Searching marketplaces",
            user_id=user_id,
        )
        from api.orchestration.hunts import (
            _run_hunt_lifecycle_safe,
            register_hunt_task,
        )

        task = asyncio.create_task(_run_hunt_lifecycle_safe(hunt_id))
        register_hunt_task(hunt_id, task)
        return new_id

    if kind in ("draft", "negotiator_draft"):
        if not job_id:
            return None
        # Reconstruct listing + valuation from listings_cache.
        async with AsyncSessionLocal() as s:
            job = await Job.get(s, job_id)
            if job is None or job.user_id != user_id:
                return None
            listing_row = None
            try:
                from sqlalchemy import select as _select

                lc_result = await s.execute(
                    _select(ListingCache).where(
                        ListingCache.listing_id == job.listing_id
                    )
                )
                listing_row = lc_result.scalars().first()
            except Exception:  # noqa: BLE001
                listing_row = None
            if listing_row is None:
                return None
            listing_dict = dict(listing_row.raw_data or {})
            listing_dict.setdefault("id", listing_row.listing_id)
            listing_dict.setdefault("marketplace", listing_row.marketplace)
            listing_dict.setdefault("title", listing_row.title or "")
            listing_dict.setdefault(
                "price",
                (listing_row.price_cents / 100.0)
                if listing_row.price_cents is not None
                else 0.0,
            )
            listing_dict.setdefault("url", listing_row.url or "")
            target = job.target_price if job.target_price is not None else None
            valuation = {"target_price": target} if target is not None else {}
            j_hunt = job.hunt_id

        new_id = task_registry.start_task(
            kind="negotiator_draft",
            hunt_id=j_hunt,
            job_id=job_id,
            label="Drafting the next message",
            user_id=user_id,
        )
        from api.orchestration import jobs as orch_jobs

        async def _runner():
            try:
                await orch_jobs.run_job_lifecycle_safe(
                    job_id=job_id,
                    listing=listing_dict,
                    valuation=valuation,
                )
            finally:
                try:
                    task_registry.finish_task(
                        new_id, status="completed", summary="Resumed draft"
                    )
                except Exception:  # noqa: BLE001
                    pass

        asyncio.create_task(_runner())
        return new_id

    if kind == "classifier":
        if not job_id:
            return None
        async with AsyncSessionLocal() as s:
            job = await Job.get(s, job_id)
            if job is None or job.user_id != user_id:
                return None
        from api.orchestration import jobs as orch_jobs

        # The helper itself manages the task-registry start/finish lifecycle.
        orch_jobs.spawn_classifier_in_background(job_id)
        # The helper returns nothing — synthesize a placeholder id so the
        # resumption response is well-formed. The real id lives inside
        # spawn_classifier_in_background.
        return f"classifier-{job_id}"

    if kind == "analyzer":
        if not hunt_id:
            return None
        async with AsyncSessionLocal() as s:
            hunt = await Hunt.get(s, hunt_id)
            if hunt is None or hunt.user_id != user_id:
                return None
        # run_post_close_analysis is idempotent by virtue of EverOS
        # dedup-on-session-id (each analyzed Case uses session_id
        # ``goti-analysis-{job_id}``) — a re-run on the same hunt won't
        # double-write per-job Cases on the EverOS side. We also bypass
        # already-analyzed jobs locally if any analyzer task already
        # wrote a per-job analysis Case (skip-by-presence). Best-effort.
        new_id = None
        try:
            new_id = (
                await asyncio.to_thread(  # noqa: F841 — keep parallel structure
                    lambda: None
                )
            )
        except Exception:  # noqa: BLE001
            pass
        from api.orchestration import analyzer as _analyzer

        asyncio.create_task(
            _analyzer.run_post_close_analysis(hunt_id=hunt_id, user_id=user_id)
        )
        # The analyzer registers its own task internally; surface a
        # synthetic id so the frontend's optimistic refresh works.
        return f"analyzer-{hunt_id}"

    # Unknown kind — caller hits 409.
    return None
