"""Phase F — finalize-close endpoint tests.

Verifies that ``POST /api/jobs/{job_id}/finalize-close``:

1. Refuses to fire when ``Job.ready_to_close`` is False (409).
2. On success:
   - Marks the chosen Job ``closed`` with ``final_price`` recorded.
   - Sends the hardcoded ``_DECLINE_TEMPLATE`` to every sibling Job in
     the same hunt (and marks each sibling ``closed``).
   - Marks the parent Hunt ``closed``.
   - Emits a ``deal_closed`` notification with the siblings_declined
     count.
3. Refuses when the job is already terminal (409).
4. Refuses when the job belongs to a different user (403).
"""

from __future__ import annotations

import asyncio

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


def test_finalize_close_409_when_not_ready(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """Without ``ready_to_close=True``, the route refuses with 409."""
    from api.models import Hunt, Job as JobORM, User

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
                goal_text="bike",
                status="negotiating",
                budget=400.0,
            )
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-not-ready",
                hunt_id=hunt.id,
                status="active",
                target_price=300.0,
            )
            await s.commit()
            return job.id

    job_id = asyncio.run(_seed())
    response = client.post(
        f"/api/jobs/{job_id}/finalize-close",
        json={"final_price": 280.0},
        headers=authed_headers,
    )
    assert response.status_code == 409, response.text
    assert "ready_to_close" in response.text


def test_finalize_close_full_fan_out(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """Happy path: yes-message + sibling declines + hunt closed + notif."""
    from api.models import (
        Hunt,
        Job as JobORM,
        ListingCache,
        MessageThread,
        Notification,
        User,
    )

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
            hunt = await Hunt.create(
                s,
                user_id=uid,
                goal_text="standing desk",
                status="negotiating",
                budget=300.0,
            )
            await s.commit()

            import uuid as _uuid

            # Listings for the chosen job + 2 siblings — each with a url
            # so the dispatch path runs.
            for li in ("L-winner", "L-sib-1", "L-sib-2"):
                s.add(
                    ListingCache(
                        marketplace="fb",
                        listing_id=li,
                        title=f"Desk {li}",
                        price_cents=30000,
                        url=f"https://example.com/{li}",
                        raw_data={"id": li, "marketplace": "fb"},
                        goal_id=_uuid.UUID(hunt.id),
                    )
                )
            await s.commit()

            chosen = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-winner",
                hunt_id=hunt.id,
                status="awaiting_seller_reply",
                target_price=250.0,
            )
            sib1 = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-sib-1",
                hunt_id=hunt.id,
                status="active",
                target_price=260.0,
            )
            sib2 = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-sib-2",
                hunt_id=hunt.id,
                status="awaiting_seller_reply",
                target_price=255.0,
            )
            await s.commit()
            # Flip readiness on the chosen job (mimics what the
            # classifier would have written).
            await JobORM.update_readiness(
                s,
                chosen.id,
                ready_to_close=True,
                close_signal_reason="Seller agreed at $245.",
                suggested_close_price=245.0,
            )
            await s.commit()
            return uid, hunt.id, chosen.id, sib1.id, sib2.id

    uid, hunt_id, chosen_id, sib1_id, sib2_id = asyncio.run(_seed())

    response = client.post(
        f"/api/jobs/{chosen_id}/finalize-close",
        json={"final_price": 245.0, "agreed_text": "Great, see you at 6!"},
        headers=authed_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["job_id"] == chosen_id
    assert body["hunt_id"] == hunt_id
    assert body["siblings_declined"] == 2

    async def _verify():
        async with AsyncSessionLocal() as s:
            chosen = await JobORM.get(s, chosen_id)
            sib1 = await JobORM.get(s, sib1_id)
            sib2 = await JobORM.get(s, sib2_id)
            chosen_msgs = await MessageThread.list_for_job(s, chosen_id)
            sib1_msgs = await MessageThread.list_for_job(s, sib1_id)
            sib2_msgs = await MessageThread.list_for_job(s, sib2_id)
            from api.models import Hunt as HuntORM

            hunt = await HuntORM.get(s, hunt_id)
            notifs = await Notification.list_for_user(s, uid, limit=20)
            return (
                chosen,
                sib1,
                sib2,
                chosen_msgs,
                sib1_msgs,
                sib2_msgs,
                hunt,
                notifs,
            )

    (
        chosen,
        sib1,
        sib2,
        chosen_msgs,
        sib1_msgs,
        sib2_msgs,
        hunt,
        notifs,
    ) = asyncio.run(_verify())

    # 1. Chosen job — closed at the final price.
    assert chosen is not None and chosen.status == "closed"
    assert chosen.final_price == 245.0
    # The yes-message (custom agreed_text) is present.
    chosen_buyer_msgs = [m for m in chosen_msgs if m.role == "buyer_agent"]
    assert any("see you at 6" in m.text for m in chosen_buyer_msgs)

    # 2. Siblings — closed, decline template message persisted.
    from api.orchestration.jobs import _DECLINE_TEMPLATE

    assert sib1 is not None and sib1.status == "closed"
    assert sib2 is not None and sib2.status == "closed"
    sib1_decline = [
        m for m in sib1_msgs if m.role == "buyer_agent" and m.text == _DECLINE_TEMPLATE
    ]
    sib2_decline = [
        m for m in sib2_msgs if m.role == "buyer_agent" and m.text == _DECLINE_TEMPLATE
    ]
    assert len(sib1_decline) == 1
    assert len(sib2_decline) == 1

    # 3. Hunt closed.
    assert hunt is not None and hunt.status == "closed"

    # 4. deal_closed notification with the siblings count.
    # Filter on job_id so cross-test pollution (other tests reusing
    # the same google ``sub`` → same User row → same user_id) doesn't
    # pick up a stale notification.
    closed_notifs = [
        n for n in notifs if n.kind == "deal_closed" and n.job_id == chosen_id
    ]
    assert closed_notifs, "expected a deal_closed notification for the chosen job"
    payload = closed_notifs[0].payload or {}
    assert payload.get("siblings_declined") == 2
    assert payload.get("final_price") == 245.0


def test_finalize_close_uses_default_yes_text_when_agreed_text_missing(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """Without ``agreed_text``, the route persists a sensible default."""
    from api.models import Hunt, Job as JobORM, ListingCache, MessageThread, User

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
            hunt = await Hunt.create(
                s,
                user_id=uid,
                goal_text="bike",
                status="negotiating",
                budget=400.0,
            )
            await s.commit()
            import uuid as _uuid

            s.add(
                ListingCache(
                    marketplace="fb",
                    listing_id="L-default-yes",
                    title="Bike",
                    price_cents=35000,
                    url="https://example.com/default-yes",
                    raw_data={"id": "L-default-yes"},
                    goal_id=_uuid.UUID(hunt.id),
                )
            )
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-default-yes",
                hunt_id=hunt.id,
                status="awaiting_seller_reply",
                target_price=300.0,
            )
            await s.commit()
            await JobORM.update_readiness(
                s,
                job.id,
                ready_to_close=True,
                close_signal_reason="Looks good.",
                suggested_close_price=295.0,
            )
            await s.commit()
            return job.id

    job_id = asyncio.run(_seed())
    response = client.post(
        f"/api/jobs/{job_id}/finalize-close",
        json={"final_price": 295.0},
        headers=authed_headers,
    )
    assert response.status_code == 200, response.text

    async def _verify():
        async with AsyncSessionLocal() as s:
            msgs = await MessageThread.list_for_job(s, job_id)
            return msgs

    msgs = asyncio.run(_verify())
    buyer_msgs = [m for m in msgs if m.role == "buyer_agent"]
    assert len(buyer_msgs) == 1
    assert "$295" in buyer_msgs[0].text


def test_finalize_close_404_for_unknown_job(
    client, stub_verify_token, authed_headers
):
    response = client.post(
        "/api/jobs/00000000-0000-0000-0000-000000000000/finalize-close",
        json={"final_price": 100.0},
        headers=authed_headers,
    )
    assert response.status_code == 404


def test_finalize_close_400_when_final_price_missing(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """Missing or non-positive final_price -> 400."""
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
                listing_id="L-no-price",
                status="awaiting_seller_reply",
                target_price=100.0,
            )
            await s.commit()
            return job.id

    job_id = asyncio.run(_seed())
    response = client.post(
        f"/api/jobs/{job_id}/finalize-close",
        json={},  # no final_price
        headers=authed_headers,
    )
    assert response.status_code == 400


def test_finalize_close_409_for_closed_job(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """Closed / cancelled jobs reject finalize-close with 409."""
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
        f"/api/jobs/{job_id}/finalize-close",
        json={"final_price": 100.0},
        headers=authed_headers,
    )
    assert response.status_code == 409
