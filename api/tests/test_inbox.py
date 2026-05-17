"""Phase M — Inbox aggregator route tests.

Covers:
- ``GET /api/inbox`` returns pending approvals + jobs ready_to_close
  across every hunt the user owns.
- Hunt-scoped approvals (``hunt-<id>-*`` request ids) are included.
- Decided / non-pending approvals are excluded.
- Closed / cancelled jobs are excluded from ready_to_close even when
  the flag was set before close.
- Each item carries enough data for the frontend to deep-link.
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


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def test_inbox_returns_empty_when_no_items(
    client, stub_verify_token, authed_headers
):
    response = client.get("/api/inbox", headers=authed_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_inbox_aggregates_pending_approvals_and_ready_to_close(
    client, stub_verify_token, authed_headers
):
    """Inbox surfaces approvals + ready-to-close jobs scoped to the user."""
    from api.models import ApprovalQueueItem, Hunt, Job, User

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
            uid = str(user.id)

            # Two hunts owned by this user.
            hunt1 = await Hunt.create(
                s,
                user_id=uid,
                goal_text="Standing desk hunt",
                status="negotiating",
                budget=300.0,
            )
            hunt2 = await Hunt.create(
                s,
                user_id=uid,
                goal_text="Bike hunt",
                status="negotiating",
                budget=500.0,
            )
            await s.commit()

            # Hunt 1: pending approval bound to a Job + ready-to-close Job.
            job1 = await Job.create(
                s,
                user_id=uid,
                listing_id="L-1",
                hunt_id=hunt1.id,
                status="awaiting_user_approval",
                target_price=200.0,
            )
            await s.commit()
            await ApprovalQueueItem.create(
                s,
                job_id=job1.id,
                draft_text="Would you take $200?",
                draft_reasoning="Anchor low",
                approval_request_id=f"job-{job1.id}-msg-0",
                request_payload={"kind": "approval_needed", "job_id": job1.id},
            )

            job1b = await Job.create(
                s,
                user_id=uid,
                listing_id="L-1b",
                hunt_id=hunt1.id,
                status="awaiting_seller_reply",
                target_price=210.0,
            )
            await s.commit()
            await Job.update_readiness(
                s,
                job1b.id,
                ready_to_close=True,
                close_signal_reason="Seller agreed at $215",
                suggested_close_price=215.0,
            )

            # A DECIDED approval in hunt1 — should NOT appear.
            decided_job = await Job.create(
                s,
                user_id=uid,
                listing_id="L-1c",
                hunt_id=hunt1.id,
                status="active",
                target_price=200.0,
            )
            await s.commit()
            decided_row = await ApprovalQueueItem.create(
                s,
                job_id=decided_job.id,
                draft_text="Already decided",
                approval_request_id=f"job-{decided_job.id}-msg-0",
            )
            await ApprovalQueueItem.resolve(s, decided_row.id, "approve")

            # Hunt 2: hunt-scoped clarifier approval (no job_id).
            await ApprovalQueueItem.create(
                s,
                job_id=None,
                draft_text="What's your budget?",
                approval_request_id=f"hunt-{hunt2.id}-budget",
                request_payload={
                    "kind": "clarifying_question",
                    "hunt_id": hunt2.id,
                },
            )

            # Closed job with ready_to_close flag — should NOT appear.
            await Job.create(
                s,
                user_id=uid,
                listing_id="L-closed",
                hunt_id=hunt1.id,
                status="closed",
                target_price=200.0,
            )
            # The Job created above is "closed"; if we set ready_to_close
            # on top, the inbox should exclude it.
            from api.models import Job as JobORM
            closed_jobs_q = await s.execute(
                __import__("sqlalchemy").select(JobORM).where(
                    JobORM.listing_id == "L-closed", JobORM.user_id == uid
                )
            )
            closed_job = closed_jobs_q.scalars().first()
            await Job.update_readiness(
                s,
                closed_job.id,
                ready_to_close=True,
                close_signal_reason="leftover",
                suggested_close_price=200.0,
            )

            await s.commit()
            return uid, hunt1.id, hunt2.id, job1.id, job1b.id

    uid, hunt1_id, hunt2_id, job1_id, job1b_id = asyncio.run(_seed())

    response = client.get("/api/inbox", headers=authed_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    items = body["items"]
    assert body["total"] == len(items)

    # Should include: 1 approval for job1, 1 ready_to_close for job1b,
    # 1 hunt-scoped clarifier approval for hunt2. Total = 3.
    kinds_seen = {it["kind"] for it in items}
    assert "approval" in kinds_seen
    assert "ready_to_close" in kinds_seen
    assert len(items) == 3, (
        f"expected 3 inbox items, got {len(items)}: {items}"
    )

    job_ids_with_approvals = [
        it["job_id"] for it in items if it["kind"] == "approval"
    ]
    assert job1_id in job_ids_with_approvals

    ready_items = [it for it in items if it["kind"] == "ready_to_close"]
    assert len(ready_items) == 1
    assert ready_items[0]["job_id"] == job1b_id

    # Hunt-scoped clarifier approval present.
    hunt_scoped = [
        it
        for it in items
        if it["kind"] == "approval" and it["job_id"] is None
    ]
    assert len(hunt_scoped) == 1
    assert hunt_scoped[0]["hunt_id"] == hunt2_id
    # Chat-first rewrite: target_href now uses /c/<hunt_id> shape.
    assert f"/c/{hunt2_id}" in hunt_scoped[0]["target_href"]


def test_inbox_excludes_other_users_items(
    client, stub_verify_token, authed_headers
):
    """User A's inbox doesn't see user B's approvals."""
    from api.models import ApprovalQueueItem, Hunt, Job, User

    async def _seed():
        async with AsyncSessionLocal() as s:
            other = await User.upsert_from_google(
                s,
                {
                    "sub": "inbox-isolation-other",
                    "email": "inbox-isolation-other@example.com",
                    "name": "Other",
                },
            )
            uid = str(other.id)
            hunt = await Hunt.create(
                s,
                user_id=uid,
                goal_text="Other user hunt",
                status="negotiating",
                budget=200.0,
            )
            await s.commit()
            job = await Job.create(
                s,
                user_id=uid,
                listing_id="L-other",
                hunt_id=hunt.id,
                status="active",
                target_price=150.0,
            )
            await s.commit()
            await ApprovalQueueItem.create(
                s,
                job_id=job.id,
                draft_text="Other's draft",
                approval_request_id=f"job-{job.id}-msg-0",
            )
            await s.commit()
            return uid

    other_uid = asyncio.run(_seed())

    response = client.get("/api/inbox", headers=authed_headers)
    assert response.status_code == 200
    body = response.json()
    for item in body["items"]:
        # Items should never carry an other-user hunt's job_id; the test
        # user (stub_verify_token) is "test-sub" and the seed used a
        # different sub.
        assert item.get("hunt_title") != "Other user hunt"
