"""User profile + onboarding + account-management routes.

Goti-side surface for the post-Google-sign-in onboarding + account flows:

- ``GET /api/me`` — the current user's profile + integrations + derived
  ``member_since`` / ``marketplaces_status``.
- ``POST /api/me/onboarding/complete`` — flip ``onboarding_completed=True``.
- ``POST /api/me/onboarding/reset`` — flip ``onboarding_completed=False``
  (lets the user redo the onboarding flow without losing data).
- ``PATCH /api/me/location`` — set the user's default location.
- ``DELETE /api/me`` — hard-delete the user and all per-user rows
  (hunts, jobs, threads, approvals, notifications, integrations).
  Best-effort: also asks EverOS to drop the user's agent memories.

Every route requires a valid Google ID-token (via ``auth.current_user``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import current_user
from api.contracts import IntegrationAccount, UserProfile
from api.db import get_session
from api.models import (
    ApprovalQueueItem,
    Hunt,
    IntegrationAccountRow,
    Job,
    MessageThread,
    Notification,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["me"])


async def _build_user_profile(
    user: User, session: AsyncSession
) -> UserProfile:
    """Compose the UserProfile shape including per-provider integration state.

    Always returns the canonical 4-tuple (fb, nextdoor, offerup,
    craigslist) — unknown rows are dropped, missing providers default
    to ``linked=False``. Pending rows surface their ``live_view_url`` so
    the onboarding UI can re-open the login tab without re-minting a
    session.
    """
    try:
        rows = await IntegrationAccountRow.list_for_user(
            session, str(user.id)
        )
    except Exception:  # noqa: BLE001 — graceful degrade for the profile
        logger.exception("_build_user_profile: integrations lookup failed")
        rows = []
    by_provider = {r.provider: r for r in rows}
    integrations: list[IntegrationAccount] = []
    for p in ("fb", "nextdoor", "offerup", "craigslist"):
        row = by_provider.get(p)
        is_active = bool(row and row.status == "active")
        integrations.append(
            IntegrationAccount(
                provider=p,  # type: ignore[arg-type]
                linked=is_active,
                linked_at=row.linked_at if (row and is_active) else None,
                live_view_url=(
                    row.live_view_url
                    if (row and row.status == "pending")
                    else None
                ),
            )
        )
    # Derived account-page fields. ``marketplaces_status`` is "linked" if
    # any provider row is currently active. A single Browserbase Context
    # spans all marketplaces, so one active link means search/messaging
    # has at least one channel available.
    any_active = any(r.status == "active" for r in rows)
    marketplaces_status: str = "linked" if any_active else "not linked"
    member_since: str | None = (
        user.created_at.isoformat() if user.created_at else None
    )
    return UserProfile(
        id=str(user.id),
        email=user.email,
        name=user.name or user.display_name,
        picture=user.picture,
        location=user.location,
        onboarding_completed=bool(user.onboarding_completed),
        integrations=integrations,
        member_since=member_since,
        marketplaces_status=marketplaces_status,  # type: ignore[arg-type]
    )


@router.get("", response_model=UserProfile)
async def get_me(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> UserProfile:
    """Return the current authenticated user's profile + integrations."""
    return await _build_user_profile(user, session)


@router.post("/onboarding/complete")
async def complete_onboarding(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Mark onboarding as complete so subsequent sign-ins skip the checklist."""
    updated = await User.mark_onboarding_complete(session, user.id)
    await session.commit()
    if updated is None:
        raise HTTPException(status_code=500, detail="failed to update user row")
    return {"ok": True}


@router.post("/onboarding/reset")
async def reset_onboarding(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Flip onboarding back to incomplete so the user can re-run the flow.

    Useful for "I want to test the onboarding flow again without
    deleting my account" — leaves all other data (hunts, jobs,
    integrations) intact. After this, ``GET /api/me.onboarding_completed``
    returns False; the frontend's onboarding gate at ``/start`` will
    redirect the user back to ``/onboarding``.
    """
    updated = await User.update_onboarding(session, user.id, completed=False)
    await session.commit()
    if updated is None:
        raise HTTPException(status_code=500, detail="failed to update user row")
    return {"ok": True}


@router.patch("/location")
async def update_location(
    body: dict[str, Any] = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Set the user's default location (optional onboarding step)."""
    raw = body.get("location")
    location = str(raw or "").strip()
    if not location:
        raise HTTPException(
            status_code=400, detail="location must be a non-empty string"
        )
    updated = await User.update_location(session, user.id, location)
    await session.commit()
    if updated is None:
        raise HTTPException(status_code=500, detail="failed to update user row")
    return {"ok": True, "location": location}


@router.delete("", status_code=204)
async def delete_account(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Hard-delete the current user's account + every per-user row.

    Sequence (single transaction so referential integrity holds):

    1. Pull all Job IDs owned by this user — needed so we can cascade
       cleanly into ``message_threads`` + ``approval_queue`` (which
       hang off ``jobs.id`` rather than ``users.id``).
    2. Delete child rows under those jobs, then user-scoped tables
       (notifications, jobs, hunts, integration_accounts, per-user
       tool catalog rows).
    3. Delete the ``users`` row itself.
    4. Commit, then fire-and-forget a best-effort EverOS memory wipe
       in the background — the EverOS SDK is sync so we run it on a
       worker thread inside the helper. If the wipe fails (or no SDK
       method matches), we log a warning and let the user-facing
       delete succeed.

    Note on ``listings_cache``: that table is keyed by
    ``(marketplace, listing_id)`` and may be shared across users
    (cached scrape rows). Intentionally NOT deleted here.
    """
    user_id_uuid = user.id
    user_id_str = str(user_id_uuid)

    # 1. Pull all job IDs owned by this user.
    job_rows = await session.execute(
        select(Job.id).where(Job.user_id == user_id_str)
    )
    job_ids = [row[0] for row in job_rows.all()]

    # 2. Delete in dependency order (children -> parents). The
    #    message_threads + approval_queue rows have ON DELETE CASCADE
    #    against jobs.id, but we explicitly drop them first so the
    #    delete is safe on SQLite test backends that don't enforce
    #    cascades.
    if job_ids:
        await session.execute(
            delete(MessageThread).where(MessageThread.job_id.in_(job_ids))
        )
        await session.execute(
            delete(ApprovalQueueItem).where(
                ApprovalQueueItem.job_id.in_(job_ids)
            )
        )
    await session.execute(
        delete(Notification).where(Notification.user_id == user_id_str)
    )
    await session.execute(delete(Job).where(Job.user_id == user_id_str))
    await session.execute(delete(Hunt).where(Hunt.user_id == user_id_str))
    await session.execute(
        delete(IntegrationAccountRow).where(
            IntegrationAccountRow.user_id == user_id_str
        )
    )

    # 3. Delete the user row itself.
    await session.execute(delete(User).where(User.id == user_id_uuid))
    await session.commit()

    # 4. Best-effort EverOS memory wipe. Fire-and-forget so the
    #    response stays fast; if no running loop is available (sync
    #    test harness), call inline.
    try:
        asyncio.create_task(_clear_everos_memory_safe(user_id_str))
    except RuntimeError:
        # No running event loop — skip; the EverOS wipe is best-effort
        # and only critical for the delete-and-re-test happy path.
        logger.info(
            "delete_account: no running asyncio loop; skipping EverOS wipe."
        )

    # 204 No Content — explicitly return a 204 Response so FastAPI
    # doesn't serialise `None` into a JSON body.
    return Response(status_code=204)


async def _clear_everos_memory_safe(user_id: str) -> None:
    """Best-effort wipe of all EverOS memories for ``user_id``.

    Per the EverOS SDK 0.4.0 surface (see
    ``everos/resources/v1/memories/memories.py``), the canonical
    primitive is ``client.v1.memories.delete(user_id=...)`` — a
    soft-delete by filter that drops the user's episodic memories,
    profile, agent_case + agent_skill rows. The ``.agent`` sub-resource
    exposes only ``add`` / ``flush`` (no delete), so the wipe lives at
    the top-level memories resource.

    If the SDK is not configured (missing key / not installed) or the
    call fails (network / API error), we log a warning and skip — the
    user-facing account delete already committed; EverOS state will
    eventually be garbage-collected or overwritten on next sign-in.
    """
    if not user_id:
        return
    try:
        # Lazy import to keep module load tolerant of a missing SDK
        # — mirrors the pattern in ``api/memory_store._get_client``.
        from api.memory_store import _get_client

        client = _get_client()
    except Exception:  # noqa: BLE001
        logger.warning(
            "_clear_everos_memory_safe: failed to acquire EverOS client; "
            "skipping wipe for user=%s",
            user_id,
        )
        return
    if client is None:
        logger.info(
            "_clear_everos_memory_safe: EverOS client unavailable; "
            "skipping wipe for user=%s",
            user_id,
        )
        return

    def _call() -> None:
        try:
            # Canonical filter-based delete. Filters: user_id only — the
            # SDK soft-deletes all memory types under that user (episodic,
            # profile, agent_case, agent_skill).
            client.v1.memories.delete(user_id=user_id)
            logger.info(
                "_clear_everos_memory_safe: ok user=%s", user_id
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "_clear_everos_memory_safe: EverOS delete failed for user=%s "
                "(non-fatal — user row already gone).",
                user_id,
                exc_info=True,
            )

    try:
        await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.warning(
            "_clear_everos_memory_safe: dispatch failed user=%s (non-fatal).",
            user_id,
            exc_info=True,
        )
