"""Phase D — decoupled job lifecycle tests.

Verifies that:
1. ``POST /api/hunts/{hunt_id}/jobs`` creates a Job row but does NOT
   spawn the negotiator (no ``run_job_lifecycle_safe`` invocation).
2. ``POST /api/jobs/{job_id}/draft-next`` DOES trigger the lifecycle.

The lifecycle itself is patched per-test so we observe whether it was
called without executing its real LLM / browser work.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

# Disable Postgres-only alembic migrations during test boot (SQLite path).
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


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def test_post_hunts_jobs_does_not_spawn_lifecycle(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """Creating a Job under a Hunt MUST NOT auto-spawn ``run_job_lifecycle_safe``.

    Phase D AC: the negotiator only fires when the user explicitly clicks
    "Start negotiating" → ``POST /api/jobs/{id}/draft-next``.
    """
    from api.models import Hunt, ListingCache, User

    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.get_by_google_sub(s, "test-sub") or (
                await User.upsert_from_google(
                    s,
                    {
                        "sub": "test-sub",
                        "email": "test@example.com",
                        "name": "Test",
                    },
                )
            )
            hunt = await Hunt.create(
                s,
                user_id=str(user.id),
                goal_text="standing desk under $250",
                status="awaiting_picks",
                budget=250.0,
            )
            await s.commit()
            # Persist a listing for this hunt to ``listings_cache`` so
            # POST /hunts/{id}/jobs's sanity check passes.
            import uuid as _uuid

            row = ListingCache(
                marketplace="fb",
                listing_id="L-decoupled-1",
                title="FlexiSpot E7 frame",
                price_cents=19900,
                url="https://example.com/decoupled",
                raw_data={"id": "L-decoupled-1", "marketplace": "fb"},
                goal_id=_uuid.UUID(hunt.id),
            )
            s.add(row)
            await s.commit()
            return hunt.id

    hunt_id = asyncio.run(_seed())

    # Patch run_job_lifecycle_safe at the orchestration module level
    # since stub_browserbase has already stubbed it; we need to verify
    # the route doesn't call it. The conftest stubs it to a no-op; we
    # replace with an AsyncMock to count calls.
    from api.orchestration import jobs as orch_jobs

    fake_lifecycle = AsyncMock(return_value=None)
    with patch.object(orch_jobs, "run_job_lifecycle_safe", fake_lifecycle):
        response = client.post(
            f"/api/hunts/{hunt_id}/jobs",
            json={"listing_id": "L-decoupled-1"},
            headers=authed_headers,
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    assert isinstance(body["job_id"], str)
    # The KEY assertion: no lifecycle spawn happened on Job create.
    assert fake_lifecycle.await_count == 0, (
        "POST /api/hunts/{id}/jobs must NOT auto-spawn run_job_lifecycle_safe; "
        "the negotiator only fires on /api/jobs/{id}/draft-next now."
    )


def test_post_draft_next_spawns_lifecycle(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """``POST /api/jobs/{job_id}/draft-next`` DOES spawn the lifecycle.

    The flip side of the decoupling — the explicit user click on the
    deal page should still kick off a draft.
    """
    from api.models import Hunt, Job as JobORM, ListingCache, User

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
                goal_text="bike under $400",
                status="negotiating",
                budget=400.0,
            )
            await s.commit()
            import uuid as _uuid

            row = ListingCache(
                marketplace="fb",
                listing_id="L-draft-next",
                title="Trek bike",
                price_cents=35000,
                url="https://example.com/draft-next",
                raw_data={"id": "L-draft-next", "marketplace": "fb"},
                goal_id=_uuid.UUID(hunt.id),
            )
            s.add(row)
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-draft-next",
                hunt_id=hunt.id,
                status="active",
                target_price=300.0,
            )
            await s.commit()
            return job.id

    job_id = asyncio.run(_seed())

    from api.orchestration import jobs as orch_jobs

    fake_lifecycle = AsyncMock(return_value=None)
    with patch.object(orch_jobs, "run_job_lifecycle_safe", fake_lifecycle):
        response = client.post(
            f"/api/jobs/{job_id}/draft-next",
            headers=authed_headers,
        )
        # Let the spawned task run so the AsyncMock observes the call.
        # The route uses asyncio.create_task; we need to give the loop
        # a tick.
        asyncio.run(asyncio.sleep(0))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["job_id"] == job_id
    assert body["spawned"] is True

    # The lifecycle was spawned (even though we patched it to no-op).
    # asyncio.create_task starts the coroutine asynchronously — by now
    # it should have been awaited.
    assert fake_lifecycle.await_count >= 1, (
        "POST /api/jobs/{id}/draft-next must spawn run_job_lifecycle_safe."
    )


def test_draft_next_returns_404_for_unknown_job(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """Unknown job_id -> 404."""
    response = client.post(
        "/api/jobs/00000000-0000-0000-0000-000000000000/draft-next",
        headers=authed_headers,
    )
    assert response.status_code == 404


def test_draft_next_returns_409_for_closed_job(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """Closed / cancelled jobs reject draft-next with 409."""
    from api.models import Job as JobORM, User

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
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-closed",
                status="closed",
                target_price=100.0,
            )
            await s.commit()
            return job.id

    job_id = asyncio.run(_seed())
    response = client.post(
        f"/api/jobs/{job_id}/draft-next", headers=authed_headers
    )
    assert response.status_code == 409
