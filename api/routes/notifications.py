"""Notifications: list + SSE stream + read-marker routes.

Backed by the ``notifications`` table (``api/models.py``) + the in-memory
queue (``api/notifications.py``). The control-plane bridge
(``api/routes/agent_bridge.py``) is the primary writer; orchestration code
(``api/orchestration/jobs.py``) also enqueues notifications for non-pause
events in later passes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api import notifications as notif_queue
from api.auth import current_user, optional_current_user
from api.db import AsyncSessionLocal, get_session
from api.models import Notification, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

HEARTBEAT_INTERVAL = 30.0


@router.get("")
async def list_notifications(
    statuses: Optional[str] = Query(
        default=None,
        description="Comma-separated subset of statuses to include (e.g. 'unread,read').",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return up to ``limit`` recent notifications for the current user.

    Without ``statuses`` the default is the union of ``unread`` +
    ``read`` (so terminal ``resolved`` / ``dismissed`` rows stay
    archived and don't clutter the inbox).
    """
    status_list = (
        [s.strip() for s in statuses.split(",") if s.strip()]
        if statuses
        else ["unread", "read"]
    )
    rows = await Notification.list_for_user(
        session, str(user.id), statuses=status_list, limit=limit
    )
    return [r.to_event_dict() for r in rows]


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await Notification.get(session, notification_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"unknown notification_id: {notification_id}"
        )
    if row.user_id != str(user.id):
        raise HTTPException(
            status_code=403,
            detail="notification does not belong to the current user",
        )
    updated = await Notification.mark_read(session, notification_id)
    await session.commit()
    return {"ok": True, "notification": (updated or row).to_event_dict()}


async def _stream_for_user(user_id: str) -> AsyncGenerator[str, None]:
    """SSE generator: initial snapshot + live push events + 30s pings.

    On connect:
    1. Open a fresh DB session and yield every ``unread`` row for the user
       as ``event: notification`` (one event per row).
    2. Subscribe to the in-memory queue and forward every matching event
       as ``event: notification``.
    3. Emit ``event: ping`` every 30s without traffic.
    4. Exit on client disconnect (``CancelledError``).
    """
    # ---- initial snapshot ----
    try:
        async with AsyncSessionLocal() as session:
            rows = await Notification.list_unread_for_user(session, user_id, limit=100)
        for row in reversed(rows):  # send oldest-first within the snapshot
            yield (
                "event: notification\n"
                f"data: {json.dumps(row.to_event_dict())}\n\n"
            )
    except Exception:  # noqa: BLE001 — initial snapshot failure should not break the stream
        logger.exception(
            "notifications._stream_for_user: snapshot failed for user=%s", user_id
        )

    last_yield = time.time()

    async with notif_queue.subscribe(user_id) as queue:
        # First emit one ping so clients can confirm the channel is open
        # immediately even when there are zero unread notifications.
        yield "event: ping\ndata: {}\n\n"
        last_yield = time.time()
        while True:
            try:
                wait_for = max(0.1, HEARTBEAT_INTERVAL - (time.time() - last_yield))
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=wait_for)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    last_yield = time.time()
                    continue
                yield (
                    "event: notification\n"
                    f"data: {json.dumps(event)}\n\n"
                )
                last_yield = time.time()
            except asyncio.CancelledError:
                logger.info(
                    "notifications._stream_for_user: client disconnected user=%s",
                    user_id,
                )
                raise
            except Exception:  # noqa: BLE001 — keep the stream alive on transient errors
                logger.exception(
                    "notifications._stream_for_user: loop error for user=%s",
                    user_id,
                )
                await asyncio.sleep(1.0)


@router.get("/stream")
async def stream_notifications(
    user: Optional[User] = Depends(optional_current_user),
) -> StreamingResponse:
    """Open a long-lived SSE stream scoped to the authenticated user.

    EventSource can't set Authorization headers, so the frontend passes
    the Google ID token via ``?token=...`` (handled by
    ``optional_current_user``). If the token is missing / invalid, the
    stream returns 401 — the frontend should redirect to /login.

    Includes the standard SSE no-buffer header (``X-Accel-Buffering: no``)
    so reverse proxies don't hold events back.
    """
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid token; SSE requires ?token=<google_id_token>.",
        )
    return StreamingResponse(
        _stream_for_user(str(user.id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
