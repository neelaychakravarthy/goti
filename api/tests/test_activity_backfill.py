"""Phase Q — activity backfill tests.

Confirms that the orchestration layer writes ``HuntActivityEvent``
rows for the lifecycle events the chat-first hunt page hydrates on
mount:

- ``start_task`` / ``finish_task`` (via the async ``start_task_db``
  variant) → ``task_started`` / ``task_completed`` / ``task_errored``
- ``run_post_close_analysis`` → ``analyzer_started`` /
  ``analyzer_progress`` / ``analyzer_complete``
- discovery loop → ``listing_discovered``

The chat-first ``HuntConversation`` initial-fetch via
``GET /api/hunts/{id}/activity`` reads these rows so a refresh shows
the full lifecycle even when the SSE stream wasn't open at the time
of the event.
"""

from __future__ import annotations

import asyncio

import pytest

import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]

from api.db import AsyncSessionLocal, Base, engine  # noqa: E402
from api.main import app  # noqa: E402  # required so route registration runs


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


async def _seed_hunt(user_id: str = "u-1") -> str:
    from api.models import Hunt

    async with AsyncSessionLocal() as s:
        hunt = await Hunt.create(
            s,
            user_id=user_id,
            goal_text="standing desk",
            status="discovering",
            budget=300.0,
        )
        await s.commit()
        return hunt.id


def test_start_task_db_writes_task_started_activity():
    """start_task_db inserts an activity row tagged ``task_started``."""
    from api.models import HuntActivityEvent
    from api.orchestration import tasks as task_registry

    async def _run() -> tuple[str, list]:
        hunt_id = await _seed_hunt(user_id="u-q-1")
        task_id = await task_registry.start_task_db(
            kind="discovery",
            hunt_id=hunt_id,
            label="Searching marketplaces",
            user_id="u-q-1",
        )
        async with AsyncSessionLocal() as s:
            rows = await HuntActivityEvent.list_for_hunt(s, hunt_id)
        return task_id, rows

    task_id, rows = asyncio.run(_run())
    assert task_id, "expected a task id back"
    phases = [r.phase for r in rows]
    assert "task_started" in phases, (
        f"expected task_started row; got phases={phases}"
    )


def test_finish_task_db_writes_task_completed_activity():
    """finish_task_db writes an activity row tagged ``task_completed`` /
    ``task_errored`` matching the status arg."""
    from api.models import HuntActivityEvent
    from api.orchestration import tasks as task_registry

    async def _run() -> list:
        hunt_id = await _seed_hunt(user_id="u-q-2")
        task_id = await task_registry.start_task_db(
            kind="classifier",
            hunt_id=hunt_id,
            label="Reading negotiation state",
            user_id="u-q-2",
        )
        await task_registry.finish_task_db(task_id, status="completed")
        async with AsyncSessionLocal() as s:
            return await HuntActivityEvent.list_for_hunt(s, hunt_id)

    rows = asyncio.run(_run())
    phases = [r.phase for r in rows]
    assert "task_started" in phases and "task_completed" in phases, (
        f"expected both task_started + task_completed; got {phases}"
    )


def test_record_activity_async_writes_row():
    """record_activity_async (the explicit-await variant) inserts a row."""
    from api.models import HuntActivityEvent
    from api.orchestration import tasks as task_registry

    async def _run() -> list:
        hunt_id = await _seed_hunt(user_id="u-q-3")
        await task_registry.record_activity_async(
            hunt_id=hunt_id,
            phase="listing_discovered",
            user_id="u-q-3",
            action_summary="$200 desk on FB",
            next_goal="evaluate",
            push_to_queue=False,
        )
        async with AsyncSessionLocal() as s:
            return await HuntActivityEvent.list_for_hunt(s, hunt_id)

    rows = asyncio.run(_run())
    assert any(r.phase == "listing_discovered" for r in rows), (
        f"expected listing_discovered phase; got {[r.phase for r in rows]}"
    )


def test_record_activity_async_skips_when_hunt_missing():
    """A non-existent hunt_id shouldn't blow up — the row insert is
    silently skipped (FK would fail otherwise)."""
    from api.orchestration import tasks as task_registry

    async def _run() -> None:
        await task_registry.record_activity_async(
            hunt_id="00000000-0000-0000-0000-000000000000",
            phase="task_started",
            user_id="u",
            action_summary="orphan task",
            push_to_queue=False,
        )

    # Should not raise — best-effort.
    asyncio.run(_run())


def test_run_post_close_analysis_emits_analyzer_phases(stub_verify_token):
    """``analyzer_started`` + ``analyzer_progress`` + ``analyzer_complete``
    are written when the analyzer fans out across closed jobs."""
    from unittest.mock import patch

    from api.models import (
        Hunt,
        HuntActivityEvent,
        Job as JobORM,
        ListingCache,
        MessageThread,
        User,
    )
    from api.orchestration import analyzer as orch_analyzer

    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "activity-backfill-analyzer",
                    "email": "ab@example.com",
                    "name": "AB",
                },
            )
            uid = str(user.id)
            hunt = await Hunt.create(
                s,
                user_id=uid,
                goal_text="standing desk",
                status="closed",
                budget=250.0,
            )
            await s.commit()
            import uuid as _uuid

            s.add(
                ListingCache(
                    marketplace="fb",
                    listing_id="L-Q",
                    title="Desk Q",
                    price_cents=24000,
                    url="https://example.com/L-Q",
                    raw_data={"id": "L-Q", "marketplace": "fb"},
                    goal_id=_uuid.UUID(hunt.id),
                )
            )
            await s.commit()
            j = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-Q",
                hunt_id=hunt.id,
                status="closed",
                target_price=200.0,
            )
            await JobORM.close_at_price(s, j.id, 210.0)
            await MessageThread.append(
                s, job_id=j.id, role="buyer_agent", text="Hello"
            )
            await s.commit()
            return uid, hunt.id, j.id

    uid, hunt_id, job_id = asyncio.run(_seed())

    async def _fake_invoke(method, payload, *args, **kwargs):
        return {
            "what_worked": [],
            "what_didnt": [],
            "key_moments": [],
            "tactical_lessons": [],
            "category": "test",
            "region": "",
            "confidence": 0.5,
            "outcome": payload.get("outcome"),
        }

    async def _fake_write(*, user_id, job_id, analysis):  # noqa: ANN001
        return True

    with (
        patch.object(orch_analyzer, "invoke_reasoner", _fake_invoke),
        patch.object(orch_analyzer, "_write_analyzed_case", _fake_write),
    ):
        result = asyncio.run(
            orch_analyzer.run_post_close_analysis(hunt_id=hunt_id, user_id=uid)
        )
    assert result["ok"] is True

    async def _read_rows() -> list:
        async with AsyncSessionLocal() as s:
            return await HuntActivityEvent.list_for_hunt(s, hunt_id)

    rows = asyncio.run(_read_rows())
    phases = [r.phase for r in rows]
    # We expect at least the three analyzer phases to be present.
    assert "analyzer_started" in phases, (
        f"missing analyzer_started; got {phases}"
    )
    assert "analyzer_progress" in phases, (
        f"missing analyzer_progress; got {phases}"
    )
    assert "analyzer_complete" in phases, (
        f"missing analyzer_complete; got {phases}"
    )
