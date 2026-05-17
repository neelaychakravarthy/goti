"""Phase L — async task observability registry tests.

Covers:
- ``start_task`` adds a row + returns a task_id.
- ``list_running_for_hunt`` filters by hunt.
- ``finish_task`` removes the row.
- ``finish_task`` is a no-op when called with an unknown task_id (so
  double-finish on the orchestration paths never raises).
- ``GET /api/hunts/{id}/running-tasks`` returns the live list, tenant-checked.
"""

from __future__ import annotations

import asyncio

import pytest

# Disable Postgres-only alembic migrations during test boot.
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


def test_start_finish_lifecycle_round_trips():
    from api.orchestration import tasks as task_registry

    task_id = task_registry.start_task(
        kind="discovery",
        hunt_id="hunt-1",
        label="Searching marketplaces",
        user_id="user-1",
    )
    assert isinstance(task_id, str) and task_id

    running = task_registry.list_running_for_hunt("hunt-1")
    assert len(running) == 1
    assert running[0]["task_id"] == task_id
    assert running[0]["kind"] == "discovery"
    assert running[0]["label"] == "Searching marketplaces"

    task_registry.finish_task(task_id, status="completed", summary="ok")
    assert task_registry.list_running_for_hunt("hunt-1") == []


def test_list_running_filters_by_hunt():
    from api.orchestration import tasks as task_registry

    t1 = task_registry.start_task(
        kind="discovery", hunt_id="hunt-A", label="A discovery"
    )
    t2 = task_registry.start_task(
        kind="classifier", hunt_id="hunt-B", job_id="job-x", label="B classifier"
    )

    a = task_registry.list_running_for_hunt("hunt-A")
    b = task_registry.list_running_for_hunt("hunt-B")
    assert {r["task_id"] for r in a} == {t1}
    assert {r["task_id"] for r in b} == {t2}
    assert task_registry.list_running_for_hunt("nope") == []


def test_finish_task_unknown_id_no_op():
    from api.orchestration import tasks as task_registry

    # Should not raise.
    task_registry.finish_task("nonexistent-id", status="errored")
    assert task_registry.list_running_for_hunt("anything") == []


def test_get_running_tasks_endpoint_returns_live_list(
    client, stub_verify_token, authed_headers
):
    from api.models import Hunt, User
    from api.orchestration import tasks as task_registry

    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "test-sub",
                    "email": "test@example.com",
                    "name": "Test",
                },
            )
            hunt = await Hunt.create(
                s,
                user_id=str(user.id),
                goal_text="task test",
                status="discovering",
                budget=300.0,
            )
            await s.commit()
            return str(user.id), hunt.id

    uid, hunt_id = asyncio.run(_seed())

    task_registry.start_task(
        kind="discovery",
        hunt_id=hunt_id,
        label="Searching marketplaces",
        user_id=uid,
    )

    response = client.get(
        f"/api/hunts/{hunt_id}/running-tasks", headers=authed_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    tasks = body["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["kind"] == "discovery"
    assert tasks[0]["hunt_id"] == hunt_id


def test_get_running_tasks_endpoint_403_for_wrong_user(
    client, stub_verify_token, authed_headers
):
    """Querying another user's hunt running-tasks returns 403."""
    from api.models import Hunt, User

    async def _seed():
        async with AsyncSessionLocal() as s:
            # Create a hunt owned by a DIFFERENT user.
            other = await User.upsert_from_google(
                s,
                {
                    "sub": "task-registry-403-other",
                    "email": "task-registry-403-other@example.com",
                    "name": "Other",
                },
            )
            hunt = await Hunt.create(
                s,
                user_id=str(other.id),
                goal_text="not mine",
                status="discovering",
                budget=300.0,
            )
            await s.commit()
            return hunt.id

    hunt_id = asyncio.run(_seed())

    response = client.get(
        f"/api/hunts/{hunt_id}/running-tasks", headers=authed_headers
    )
    assert response.status_code == 403
