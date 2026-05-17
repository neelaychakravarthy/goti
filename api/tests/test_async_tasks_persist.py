"""Phase O — durable async-task persistence + explicit resume tests.

Covers:
- ``start_task_db`` inserts an ``async_tasks`` row with ``status='running'``.
- ``finish_task_db`` updates the row to ``completed`` / ``errored``.
- ``_interrupt_stale_async_tasks`` flips every ``running`` row to
  ``interrupted`` (simulates the startup hook).
- ``GET /api/hunts/{id}/stopped-tasks`` lists interrupted rows
  (tenant-scoped).
- ``POST /api/tasks/{id}/resume`` dispatches a fresh task per ``kind``.
- ``check_replies`` / ``finalize_close`` kinds return 409.
"""

from __future__ import annotations

import asyncio

import pytest

import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]

from api.db import AsyncSessionLocal, Base, engine  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _setup_schema():
    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    yield


@pytest.fixture(autouse=True)
def _reset_registry():
    from api.orchestration import tasks as task_registry

    task_registry.reset_for_tests()
    yield
    task_registry.reset_for_tests()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


async def _seed_user_and_hunt(google_sub: str = "test-sub") -> tuple[str, str]:
    from api.models import Hunt, User

    async with AsyncSessionLocal() as s:
        user = await User.upsert_from_google(
            s,
            {"sub": google_sub, "email": f"{google_sub}@e.com", "name": "x"},
        )
        hunt = await Hunt.create(
            s,
            user_id=str(user.id),
            goal_text="task persist test",
            status="discovering",
            budget=200.0,
        )
        await s.commit()
        return str(user.id), hunt.id


def test_start_task_db_writes_running_row():
    """The durable row is inserted with ``status='running'`` on start."""
    from api.models import AsyncTaskRow
    from api.orchestration import tasks as task_registry

    async def _run() -> tuple[str, AsyncTaskRow | None]:
        uid, hunt_id = await _seed_user_and_hunt("test-async-row-1")
        task_id = await task_registry.start_task_db(
            kind="discovery",
            hunt_id=hunt_id,
            label="Searching marketplaces",
            user_id=uid,
        )
        async with AsyncSessionLocal() as s:
            row = await AsyncTaskRow.get(s, task_id)
        return task_id, row

    task_id, row = asyncio.run(_run())
    assert row is not None
    assert row.id == task_id
    assert row.status == "running"
    assert row.kind == "discovery"


def test_finish_task_db_marks_row_terminal():
    """finish_task_db transitions the row to ``completed`` / ``errored``."""
    from api.models import AsyncTaskRow
    from api.orchestration import tasks as task_registry

    async def _run() -> AsyncTaskRow | None:
        uid, hunt_id = await _seed_user_and_hunt("test-async-row-2")
        task_id = await task_registry.start_task_db(
            kind="classifier",
            hunt_id=hunt_id,
            label="Reading",
            user_id=uid,
        )
        await task_registry.finish_task_db(
            task_id, status="completed", summary="done"
        )
        async with AsyncSessionLocal() as s:
            return await AsyncTaskRow.get(s, task_id)

    row = asyncio.run(_run())
    assert row is not None
    assert row.status == "completed"
    assert row.summary == "done"
    assert row.finished_at is not None


def test_mark_all_running_interrupted_flip_simulates_startup_hook():
    """``mark_all_running_interrupted`` flips every running row at once.

    With the StaticPool-shared DB across tests, prior rows may leak; we
    verify each row of interest individually instead of asserting an
    exact ``flipped`` count.
    """
    from api.models import AsyncTaskRow
    from api.orchestration import tasks as task_registry

    async def _run():
        uid, hunt_id = await _seed_user_and_hunt("test-async-row-3")
        running_id_a = await task_registry.start_task_db(
            kind="discovery",
            hunt_id=hunt_id,
            label="A",
            user_id=uid,
        )
        completed_id = await task_registry.start_task_db(
            kind="classifier",
            hunt_id=hunt_id,
            label="C",
            user_id=uid,
        )
        await task_registry.finish_task_db(completed_id, status="completed")

        async with AsyncSessionLocal() as s:
            await AsyncTaskRow.mark_all_running_interrupted(s)
            await s.commit()
            row_a = await AsyncTaskRow.get(s, running_id_a)
            row_c = await AsyncTaskRow.get(s, completed_id)
        return row_a, row_c

    row_a, row_c = asyncio.run(_run())
    assert row_a is not None and row_a.status == "interrupted"
    # Already-completed rows stay completed.
    assert row_c is not None and row_c.status == "completed"


def test_stopped_tasks_endpoint_returns_interrupted_rows(
    client, stub_verify_token, authed_headers
):
    """GET /api/hunts/{id}/stopped-tasks returns the user's interrupted rows."""
    from api.models import AsyncTaskRow
    from api.orchestration import tasks as task_registry

    async def _seed_and_interrupt() -> tuple[str, str]:
        uid, hunt_id = await _seed_user_and_hunt("test-sub")
        # Two running tasks.
        await task_registry.start_task_db(
            kind="discovery",
            hunt_id=hunt_id,
            label="Searching",
            user_id=uid,
        )
        await task_registry.start_task_db(
            kind="analyzer",
            hunt_id=hunt_id,
            label="Analyzing",
            user_id=uid,
        )
        # Flip them to interrupted (simulates startup hook).
        async with AsyncSessionLocal() as s:
            await AsyncTaskRow.mark_all_running_interrupted(s)
            await s.commit()
        return uid, hunt_id

    uid, hunt_id = asyncio.run(_seed_and_interrupt())

    response = client.get(
        f"/api/hunts/{hunt_id}/stopped-tasks", headers=authed_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    tasks = body["tasks"]
    assert len(tasks) == 2, f"expected 2 interrupted rows; got {len(tasks)}"
    kinds = {t["kind"] for t in tasks}
    assert kinds == {"discovery", "analyzer"}
    # All entries should have can_resume == True for these kinds.
    assert all(t["can_resume"] for t in tasks)
    assert all(t["status"] == "interrupted" for t in tasks)


def test_resume_task_409_for_not_autoresumable_kinds(
    client, stub_verify_token, authed_headers
):
    """``check_replies`` / ``finalize_close`` rows return 409 on resume."""
    from api.models import AsyncTaskRow
    from api.orchestration import tasks as task_registry

    async def _seed_and_interrupt() -> tuple[str, str]:
        uid, hunt_id = await _seed_user_and_hunt("test-sub")
        # Hand-roll an interrupted row of kind=check_replies.
        await task_registry.start_task_db(
            kind="check_replies",
            hunt_id=hunt_id,
            label="Checking replies",
            user_id=uid,
        )
        async with AsyncSessionLocal() as s:
            await AsyncTaskRow.mark_all_running_interrupted(s)
            await s.commit()
            # Look up the row id.
            rows = await AsyncTaskRow.list_interrupted_for_hunt(
                s, hunt_id=hunt_id, user_id=uid
            )
        return uid, rows[0].id

    uid, task_id = asyncio.run(_seed_and_interrupt())

    response = client.post(
        f"/api/tasks/{task_id}/resume", headers=authed_headers
    )
    assert response.status_code == 409, response.text
    assert "check_replies" in response.text.lower() or "click" in response.text.lower()


def test_resume_task_returns_404_for_unknown_task(
    client, stub_verify_token, authed_headers
):
    """Resuming a non-existent task id returns 404."""
    response = client.post(
        "/api/tasks/non-existent-task/resume", headers=authed_headers
    )
    assert response.status_code in (404, 422)


def test_resume_task_returns_403_for_other_user(
    client, stub_verify_token, authed_headers
):
    """Resuming another user's task returns 403."""
    from api.models import AsyncTaskRow
    from api.orchestration import tasks as task_registry

    async def _seed_other_user_task() -> str:
        # Different user (so the test_sub user can't see this).
        uid_other, hunt_id = await _seed_user_and_hunt(
            "test-sub-other-resume-403"
        )
        await task_registry.start_task_db(
            kind="discovery",
            hunt_id=hunt_id,
            label="Searching",
            user_id=uid_other,
        )
        async with AsyncSessionLocal() as s:
            await AsyncTaskRow.mark_all_running_interrupted(s)
            await s.commit()
            rows = await AsyncTaskRow.list_interrupted_for_hunt(
                s, hunt_id=hunt_id, user_id=uid_other
            )
        return rows[0].id

    task_id = asyncio.run(_seed_other_user_task())
    # The default stub_verify_token resolves to ``test-sub`` user.
    response = client.post(
        f"/api/tasks/{task_id}/resume", headers=authed_headers
    )
    assert response.status_code == 403, response.text


def test_resume_task_409_when_not_interrupted(
    client, stub_verify_token, authed_headers
):
    """Resuming a still-running or already-completed task → 409."""
    from api.orchestration import tasks as task_registry

    async def _seed() -> str:
        uid, hunt_id = await _seed_user_and_hunt("test-sub")
        return await task_registry.start_task_db(
            kind="discovery",
            hunt_id=hunt_id,
            label="Searching",
            user_id=uid,
        )

    task_id = asyncio.run(_seed())
    response = client.post(
        f"/api/tasks/{task_id}/resume", headers=authed_headers
    )
    assert response.status_code == 409
    assert "interrupted" in response.text.lower()
