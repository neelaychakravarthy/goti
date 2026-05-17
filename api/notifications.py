"""In-memory pub/sub for live notification delivery.

The AgentField control-plane bridge (`api/routes/agent_bridge.py`) writes
``Notification`` rows to Postgres AND publishes them to this in-memory
queue. The SSE notifications stream (`api/routes/notifications.py`)
subscribes to the queue so users receive push notifications without
waiting for a 500ms DB poll cycle.

Design:

- One ``asyncio.Queue`` per (user_id, subscriber) pair. Multiple SSE
  connections from the same user each get their own queue, so a single
  notification fans out to every active client tab.
- ``enqueue(notification_dict)`` dispatches to every subscribed queue
  matching the notification's ``user_id`` (or all queues if the
  notification has no user_id — broadcast).
- Queues are bounded (1000) to prevent memory growth if a client stops
  draining without disconnecting. Overflow drops the oldest event with
  a log warning.
- This is process-local. Multi-instance deployments need a real pub/sub
  (Redis pub/sub, Postgres LISTEN/NOTIFY) — out of scope for this Pass.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Per-subscriber queues. Each tuple is ``(user_id, queue)``.
_SUBSCRIBERS: list[tuple[str, asyncio.Queue[dict]]] = []
_LOCK = asyncio.Lock()

# Bounded queue size — a slow client should not balloon memory.
_QUEUE_MAXSIZE = 1000


async def enqueue(notification: dict[str, Any]) -> int:
    """Publish ``notification`` to every subscriber matching its user_id.

    The ``user_id`` field is required on the dict; ``None`` / missing
    means "broadcast to every subscriber". Returns the number of queues
    the event was delivered to (useful for log + tests).

    Non-blocking: each per-queue ``put`` runs with ``put_nowait`` and
    drops the oldest event on full queues so a stalled subscriber can't
    backpressure the producer.
    """
    target_user = notification.get("user_id")
    delivered = 0
    async with _LOCK:
        subscribers = list(_SUBSCRIBERS)

    for sub_user, queue in subscribers:
        if target_user is not None and sub_user != target_user:
            continue
        try:
            queue.put_nowait(notification)
            delivered += 1
        except asyncio.QueueFull:
            # Drop the oldest event so newer ones aren't blocked.
            try:
                _ = queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(notification)
                delivered += 1
            except asyncio.QueueFull:
                logger.warning(
                    "notifications.enqueue: queue still full after drop; dropping event for user=%s",
                    sub_user,
                )
    return delivered


@asynccontextmanager
async def subscribe(user_id: str) -> AsyncIterator[asyncio.Queue[dict]]:
    """Yield a per-subscriber queue scoped to ``user_id``.

    Use as an async context manager so the queue is automatically
    unregistered on disconnect (or any exception inside the SSE
    generator).

    Example:
        async with subscribe(str(user.id)) as q:
            while True:
                evt = await q.get()
                ...
    """
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    async with _LOCK:
        _SUBSCRIBERS.append((user_id, queue))
    try:
        yield queue
    finally:
        async with _LOCK:
            try:
                _SUBSCRIBERS.remove((user_id, queue))
            except ValueError:
                pass


async def subscriber_count() -> int:
    """Return the number of active subscribers (test helper)."""
    async with _LOCK:
        return len(_SUBSCRIBERS)


async def reset_for_tests() -> None:
    """Clear all subscribers — used by tests that mutate global state."""
    async with _LOCK:
        _SUBSCRIBERS.clear()
