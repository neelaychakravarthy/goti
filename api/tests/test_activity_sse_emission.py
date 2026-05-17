"""Phase P — activity SSE emission tests.

Confirms that ``record_activity_async`` pushes onto the notifications
in-memory queue with ``kind="info"`` + ``payload.kind_tag="hunt_activity"``.
The frontend's ``useNotifications()`` consumer reads those events
and merges them into the chat conversation in real-time (replacing
the prior 3s polling on ``/api/hunts/{id}/activity``).
"""

from __future__ import annotations

import asyncio

import pytest

import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]

from api.db import AsyncSessionLocal, Base, engine  # noqa: E402
from api.main import app  # noqa: F401  # required for route registration


@pytest.fixture(scope="module", autouse=True)
def _setup_schema():
    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    yield


@pytest.fixture(autouse=True)
def _reset_state():
    from api.orchestration import tasks as task_registry

    task_registry.reset_for_tests()
    yield
    task_registry.reset_for_tests()


async def _seed_hunt(user_id: str) -> str:
    from api.models import Hunt

    async with AsyncSessionLocal() as s:
        hunt = await Hunt.create(
            s,
            user_id=user_id,
            goal_text="standing desk",
            status="discovering",
            budget=200.0,
        )
        await s.commit()
        return hunt.id


def test_record_activity_async_pushes_to_notif_queue_when_enabled():
    """``record_activity_async(push_to_queue=True)`` enqueues a
    ``hunt_activity``-tagged event onto the notifications stream."""
    from api import notifications as notif_queue
    from api.orchestration import tasks as task_registry

    captured: list[dict] = []

    async def _run() -> None:
        user_id = "u-sse-1"
        hunt_id = await _seed_hunt(user_id)
        async with notif_queue.subscribe(user_id) as q:
            await task_registry.record_activity_async(
                hunt_id=hunt_id,
                phase="listing_discovered",
                user_id=user_id,
                action_summary="$200 desk on FB",
                next_goal="evaluate",
                push_to_queue=True,
            )
            # Drain the queue (non-blocking — we just enqueued).
            try:
                while True:
                    evt = q.get_nowait()
                    captured.append(evt)
            except asyncio.QueueEmpty:
                pass

    asyncio.run(_run())
    assert any(
        evt.get("payload", {}).get("kind_tag") == "hunt_activity"
        for evt in captured
    ), f"expected hunt_activity event on the queue; got {captured!r}"
    # Spot-check shape — id prefixed, kind='info', payload carries phase.
    hunt_activity_events = [
        e for e in captured if e.get("payload", {}).get("kind_tag") == "hunt_activity"
    ]
    assert hunt_activity_events, "no hunt_activity events captured"
    e = hunt_activity_events[0]
    assert e["kind"] == "info"
    assert str(e["id"]).startswith("hunt-activity-")
    assert e["payload"]["phase"] == "listing_discovered"


def test_record_activity_async_does_not_push_when_disabled():
    """``push_to_queue=False`` skips the SSE push (DB write only)."""
    from api import notifications as notif_queue
    from api.orchestration import tasks as task_registry

    captured: list[dict] = []

    async def _run() -> None:
        user_id = "u-sse-2"
        hunt_id = await _seed_hunt(user_id)
        async with notif_queue.subscribe(user_id) as q:
            await task_registry.record_activity_async(
                hunt_id=hunt_id,
                phase="task_started",
                user_id=user_id,
                action_summary="quiet",
                push_to_queue=False,
            )
            try:
                while True:
                    captured.append(q.get_nowait())
            except asyncio.QueueEmpty:
                pass

    asyncio.run(_run())
    # No ``hunt_activity`` events should land on the queue.
    assert not any(
        evt.get("payload", {}).get("kind_tag") == "hunt_activity"
        for evt in captured
    ), f"unexpected hunt_activity event when push_to_queue=False: {captured!r}"


def test_start_task_db_emits_hunt_activity_indirectly():
    """``start_task_db`` writes a ``task_started`` activity row but doesn't
    push it (push_to_queue=False). The DB-backed row is sufficient for
    initial-hydration on the chat page."""
    from api import notifications as notif_queue
    from api.orchestration import tasks as task_registry

    captured: list[dict] = []

    async def _run() -> None:
        user_id = "u-sse-3"
        hunt_id = await _seed_hunt(user_id)
        async with notif_queue.subscribe(user_id) as q:
            await task_registry.start_task_db(
                kind="discovery",
                hunt_id=hunt_id,
                label="Searching",
                user_id=user_id,
            )
            try:
                while True:
                    captured.append(q.get_nowait())
            except asyncio.QueueEmpty:
                pass

    asyncio.run(_run())
    # ``start_task_db`` only emits a ``task_started`` notification (via
    # ``_emit_event``) — the activity row push is suppressed to avoid
    # duplicating the chat tile. So no ``hunt_activity`` kind_tag.
    hunt_activity_events = [
        e for e in captured if e.get("payload", {}).get("kind_tag") == "hunt_activity"
    ]
    assert not hunt_activity_events, (
        "start_task_db should not push hunt_activity events (the "
        "task_started notification already covers the live stream): "
        f"{hunt_activity_events!r}"
    )
    # We DO expect the existing ``task_started`` notification on the
    # queue (the in-memory task-registry path is unchanged).
    task_started_events = [
        e
        for e in captured
        if e.get("payload", {}).get("kind_tag") == "task_started"
    ]
    assert task_started_events, (
        "expected a task_started notification on the queue"
    )
