"""Phase T — per-tab badge counts on the negotiation tab strip.

``GET /api/hunts/{id}`` response carries a ``tab_badges`` dict keyed
by ``job_id``. Count per job = pending approvals + (1 if
ready_to_close else 0) + (1 if a seller message is newer than the
most-recent buyer_agent message else 0). Zero-count jobs are omitted
from the wire payload.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

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


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def test_tab_badges_zero_when_nothing_pending(
    client, stub_verify_token, authed_headers
):
    """Hunt with one active job + no approvals + no seller messages → no badge."""
    from api.models import Hunt, Job as JobORM, User

    async def _seed() -> str:
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {"sub": "test-sub", "email": "t@example.com", "name": "T"},
            )
            hunt = await Hunt.create(
                s,
                user_id=str(user.id),
                goal_text="zero badge",
                status="negotiating",
                budget=250.0,
            )
            await s.commit()
            await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-zero",
                hunt_id=hunt.id,
                status="active",
                target_price=200.0,
            )
            await s.commit()
            return hunt.id

    hunt_id = asyncio.run(_seed())
    response = client.get(f"/api/hunts/{hunt_id}", headers=authed_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "tab_badges" in body
    assert body["tab_badges"] == {}, (
        f"expected empty tab_badges; got {body['tab_badges']}"
    )


def test_tab_badges_counts_pending_approvals(
    client, stub_verify_token, authed_headers
):
    """Each undecided approval row on a job contributes 1 to the count."""
    from api.models import ApprovalQueueItem, Hunt, Job as JobORM, User

    async def _seed() -> tuple[str, str]:
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {"sub": "test-sub", "email": "t@example.com", "name": "T"},
            )
            hunt = await Hunt.create(
                s,
                user_id=str(user.id),
                goal_text="badge approvals",
                status="negotiating",
                budget=250.0,
            )
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-A",
                hunt_id=hunt.id,
                status="active",
                target_price=200.0,
            )
            await ApprovalQueueItem.create(
                s,
                job_id=job.id,
                draft_text="draft 1",
                approval_request_id=f"job-{job.id}-msg-1",
            )
            await ApprovalQueueItem.create(
                s,
                job_id=job.id,
                draft_text="draft 2",
                approval_request_id=f"job-{job.id}-msg-2",
            )
            await s.commit()
            return hunt.id, job.id

    hunt_id, job_id = asyncio.run(_seed())
    response = client.get(f"/api/hunts/{hunt_id}", headers=authed_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tab_badges"].get(job_id) == 2, (
        f"expected 2 pending approvals; got {body['tab_badges']}"
    )


def test_tab_badges_adds_one_for_ready_to_close(
    client, stub_verify_token, authed_headers
):
    """``Job.ready_to_close=True`` adds 1 to the count."""
    from api.models import Hunt, Job as JobORM, User

    async def _seed() -> tuple[str, str]:
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {"sub": "test-sub", "email": "t@example.com", "name": "T"},
            )
            hunt = await Hunt.create(
                s,
                user_id=str(user.id),
                goal_text="badge ready",
                status="negotiating",
                budget=250.0,
            )
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-R",
                hunt_id=hunt.id,
                status="active",
                target_price=200.0,
            )
            await JobORM.update_readiness(
                s,
                job.id,
                ready_to_close=True,
                close_signal_reason="agreed",
                suggested_close_price=180.0,
            )
            await s.commit()
            return hunt.id, job.id

    hunt_id, job_id = asyncio.run(_seed())
    response = client.get(f"/api/hunts/{hunt_id}", headers=authed_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tab_badges"].get(job_id) == 1, (
        f"expected 1 (ready_to_close); got {body['tab_badges']}"
    )


def test_tab_badges_adds_one_for_unread_seller_reply(
    client, stub_verify_token, authed_headers
):
    """A seller message newer than the most-recent buyer_agent message
    adds 1."""
    from api.models import Hunt, Job as JobORM, MessageThread, User

    async def _seed() -> tuple[str, str]:
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {"sub": "test-sub", "email": "t@example.com", "name": "T"},
            )
            hunt = await Hunt.create(
                s,
                user_id=str(user.id),
                goal_text="badge seller",
                status="negotiating",
                budget=250.0,
            )
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-S",
                hunt_id=hunt.id,
                status="awaiting_seller_reply",
                target_price=200.0,
            )
            # Buyer message first.
            buyer = await MessageThread.append(
                s,
                job_id=job.id,
                role="buyer_agent",
                text="Hi, would $180 work?",
            )
            buyer.sent_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            # Seller replied AFTER the buyer.
            seller = await MessageThread.append(
                s,
                job_id=job.id,
                role="seller",
                text="Sure!",
            )
            seller.sent_at = datetime.now(timezone.utc)
            await s.commit()
            return hunt.id, job.id

    hunt_id, job_id = asyncio.run(_seed())
    response = client.get(f"/api/hunts/{hunt_id}", headers=authed_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tab_badges"].get(job_id) == 1, (
        f"expected 1 (unread seller reply); got {body['tab_badges']}"
    )


def test_tab_badges_omits_closed_jobs(
    client, stub_verify_token, authed_headers
):
    """``closed`` / ``cancelled`` jobs don't show up in the badge dict."""
    from api.models import Hunt, Job as JobORM, MessageThread, User

    async def _seed() -> str:
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {"sub": "test-sub", "email": "t@example.com", "name": "T"},
            )
            hunt = await Hunt.create(
                s,
                user_id=str(user.id),
                goal_text="badge closed",
                status="closed",
                budget=250.0,
            )
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-C",
                hunt_id=hunt.id,
                status="closed",
                target_price=200.0,
            )
            # Even if it has a "newer seller" message — should be ignored.
            await MessageThread.append(
                s, job_id=job.id, role="seller", text="Late reply"
            )
            await s.commit()
            return hunt.id

    hunt_id = asyncio.run(_seed())
    response = client.get(f"/api/hunts/{hunt_id}", headers=authed_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tab_badges"] == {}, (
        f"expected closed jobs to be filtered out; got {body['tab_badges']}"
    )
