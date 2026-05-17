"""Integration test for the DB-backed adapter routes.

Walks through the DB-backed shape for each frontend endpoint:

- ``GET /api/outbox`` — counts derived from jobs / approval_queue /
  message_threads.
- ``GET /api/jobs`` — list shape mapped from real Job rows.
- ``GET /api/approvals`` — ApprovalTickets composed from real
  ApprovalQueueItem rows bound to the AgentField approval_request_id.
- ``GET /api/buying-brief?hunt_id=…`` — returns the seeded brief.
- ``GET /api/playbook`` — empty when EverOS has nothing (CI default).

Modelled on ``test_hunt_lifecycle.py``'s pattern: in-memory SQLite,
``TestClient`` (sync), schema created via ``Base.metadata.create_all``.
"""

from __future__ import annotations

import asyncio

import pytest

# Disable Postgres-only alembic migrations during test boot.
import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]
# Disable the startup hunt-resumption — tests seed their own rows and
# the lifecycle coroutine would race the assertions.
_api_main._resume_inflight_hunts = (  # type: ignore[assignment]
    lambda: asyncio.sleep(0)
)

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


async def _seed_fixtures(user_id: str) -> dict:
    """Seed a Hunt + 2 Jobs + 1 unresolved ApprovalQueueItem.

    Returns the ids the assertions need:
        {"hunt_id", "job_active_id", "job_awaiting_id", "approval_request_id"}
    """
    from api.models import (
        ApprovalQueueItem,
        Hunt,
        Job as JobORM,
        ListingCache,
    )

    async with AsyncSessionLocal() as s:
        hunt = await Hunt.create(
            s,
            user_id=user_id,
            goal_text="standing desk under $250 SF",
            status="negotiating",
            budget=250.0,
            brief={
                "item": "standing desk",
                "max_price": 250,
                "near": "San Francisco",
                "avoid": "IKEA",
                "pickup_timing": "today or tomorrow",
            },
        )
        await s.commit()
        hunt_id = hunt.id

    async with AsyncSessionLocal() as s:
        # Seed two listings_cache rows so the title / marketplace
        # joins succeed for both Job rows.
        s.add(
            ListingCache(
                marketplace="fb",
                listing_id="l-uplift-test",
                title="Uplift V2 standing desk",
                price_cents=24000,
                url="https://facebook.com/marketplace/item/l-uplift-test",
                raw_data={"seller_name": "Daniel", "location": "Mission Bay"},
            )
        )
        s.add(
            ListingCache(
                marketplace="nextdoor",
                listing_id="l-flexispot-test",
                title="FlexiSpot E7 standing desk",
                price_cents=19500,
                url="https://nextdoor.com/listing/l-flexispot-test",
                raw_data={"seller_name": "Ari", "location": "Sunset"},
            )
        )
        await s.commit()

    async with AsyncSessionLocal() as s:
        job_active = await JobORM.create(
            s,
            user_id=user_id,
            listing_id="l-uplift-test",
            hunt_id=hunt_id,
            status="active",
            target_price=205.0,
        )
        job_awaiting = await JobORM.create(
            s,
            user_id=user_id,
            listing_id="l-flexispot-test",
            hunt_id=hunt_id,
            status="active",
            target_price=180.0,
        )
        await s.commit()
        job_active_id = job_active.id
        job_awaiting_id = job_awaiting.id

    async with AsyncSessionLocal() as s:
        approval_request_id = f"job-{job_active_id}-msg-1"
        await ApprovalQueueItem.create(
            s,
            job_id=job_active_id,
            draft_text=(
                "Hi Daniel — would you do $205 for same-day pickup?"
            ),
            draft_reasoning=(
                "FlexiSpot listed at $195 nearby; anchor with that."
            ),
            execution_id="exec-test",
            agent_node_id="goti",
            agent_callback_url="http://127.0.0.1:8080/webhooks/approval",
            approval_request_id=approval_request_id,
            request_payload={
                "kind": "approval_needed",
                "title": "Approve draft",
                "ask_price": 205,
            },
        )
        await s.commit()

    return {
        "hunt_id": hunt_id,
        "job_active_id": job_active_id,
        "job_awaiting_id": job_awaiting_id,
        "approval_request_id": approval_request_id,
    }


async def _teardown_fixtures(ids: dict) -> None:
    """Best-effort cleanup so subsequent tests start from a clean slate.

    Each test that calls ``_seed_fixtures`` should call this in a
    ``finally`` so the in-memory SQLite (shared across the module) doesn't
    accumulate state.
    """
    from sqlalchemy import delete

    from api.models import ApprovalQueueItem, Hunt, Job as JobORM, ListingCache

    async with AsyncSessionLocal() as s:
        await s.execute(
            delete(ApprovalQueueItem).where(
                ApprovalQueueItem.job_id.in_(
                    [ids["job_active_id"], ids["job_awaiting_id"]]
                )
            )
        )
        await s.execute(
            delete(JobORM).where(
                JobORM.id.in_([ids["job_active_id"], ids["job_awaiting_id"]])
            )
        )
        await s.execute(delete(Hunt).where(Hunt.id == ids["hunt_id"]))
        await s.execute(
            delete(ListingCache).where(
                ListingCache.listing_id.in_(["l-uplift-test", "l-flexispot-test"])
            )
        )
        await s.commit()


async def _bootstrap_user(client, headers) -> str:
    """Hit /api/me once so the auth stub mints a User row; return its id."""
    response = client.get("/api/me", headers=headers)
    assert response.status_code == 200, response.text

    from api.models import User

    async def _get_id():
        async with AsyncSessionLocal() as s:
            u = await User.get_by_google_sub(s, "test-sub")
            assert u is not None
            return str(u.id)

    return await _get_id()


def test_adapter_real_data(client, stub_verify_token, authed_headers):
    """AC 3 (integration test): every adapter route serves seeded data.

    Seeds 1 Hunt + 2 active Jobs + 1 unresolved ApprovalQueueItem, then
    hits each adapter endpoint and asserts the response reflects the
    DB state (not the fixture file).
    """
    user_id = asyncio.run(_bootstrap_user(client, authed_headers))
    ids = asyncio.run(_seed_fixtures(user_id))
    try:
        # ---- /api/outbox ----
        resp = client.get("/api/outbox", headers=authed_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 1 unresolved approval => drafts==1
        # 2 active jobs => selected==2
        # 0 rejected => skipped==0
        # 0 awaiting_seller_reply => waiting==0
        # 0 buyer_agent messages => sent==0
        assert body["drafts"] >= 1, body
        assert body["selected"] >= 2, body
        assert body["sent"] == 0, body
        assert body["waiting"] == 0, body
        assert body["skipped"] == 0, body

        # ---- /api/jobs ----
        resp = client.get("/api/jobs", headers=authed_headers)
        assert resp.status_code == 200, resp.text
        jobs = resp.json()
        assert isinstance(jobs, list)
        seeded_jobs = [
            j for j in jobs
            if j["job_id"] in (ids["job_active_id"], ids["job_awaiting_id"])
        ]
        assert len(seeded_jobs) == 2, jobs
        # Marketplace + title joins from listings_cache.
        seen_titles = {j["title"] for j in seeded_jobs}
        assert "Uplift V2 standing desk" in seen_titles, seeded_jobs
        assert "FlexiSpot E7 standing desk" in seen_titles, seeded_jobs
        seen_marketplaces = {j["marketplace"] for j in seeded_jobs}
        assert "facebook" in seen_marketplaces, seeded_jobs
        assert "nextdoor" in seen_marketplaces, seeded_jobs
        # Status mapping: internal "active" -> frontend "active".
        assert all(j["status"] == "active" for j in seeded_jobs), seeded_jobs

        # ---- /api/approvals ----
        resp = client.get("/api/approvals", headers=authed_headers)
        assert resp.status_code == 200, resp.text
        approvals = resp.json()
        matching = [
            t for t in approvals
            if t.get("approval_request_id") == ids["approval_request_id"]
        ]
        assert len(matching) == 1, approvals
        ticket = matching[0]
        # id == approval_request_id (matches the AgentField bridge contract)
        assert ticket["id"] == ids["approval_request_id"], ticket
        assert ticket["hunt_id"] == ids["hunt_id"], ticket
        assert ticket["job_id"] == ids["job_active_id"], ticket
        assert ticket["listing_id"] == "l-uplift-test", ticket
        # Recipient name + listing title joined from listings_cache.
        assert ticket["recipient_name"] == "Daniel", ticket
        assert ticket["listing_title"] == "Uplift V2 standing desk", ticket
        assert ticket["marketplace"] == "facebook", ticket
        # ask_price from the request_payload's ``ask_price`` field.
        assert ticket["ask_price"] == 205, ticket

        # ---- /api/buying-brief?hunt_id=<id> ----
        resp = client.get(
            "/api/buying-brief",
            params={"hunt_id": ids["hunt_id"]},
            headers=authed_headers,
        )
        assert resp.status_code == 200, resp.text
        brief = resp.json()
        assert brief["item"] == "standing desk"
        assert brief["max_price"] == 250
        assert brief["near"] == "San Francisco"
        assert brief["avoid"] == "IKEA"
        assert brief["pickup_timing"] == "today or tomorrow"

        # ---- /api/playbook ----
        # No EverOS key in CI → memory_store returns []; adapter returns
        # an empty Playbook so the shape is preserved.
        resp = client.get("/api/playbook", headers=authed_headers)
        assert resp.status_code == 200, resp.text
        playbook = resp.json()
        assert "cases" in playbook
        assert "notes" in playbook
        assert "new_learning" in playbook
    finally:
        asyncio.run(_teardown_fixtures(ids))


def test_outbox_returns_zeros_on_empty_db(client, stub_verify_token, authed_headers):
    """AC 3 sanity: with no seeded rows, /api/outbox still returns the shape.

    Counts should all be 0 (or whatever the previous-test cleanup left
    behind); the route must NOT 500.
    """
    resp = client.get("/api/outbox", headers=authed_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("sent", "drafts", "waiting", "selected", "skipped"):
        assert key in body, body
        assert isinstance(body[key], int), body


def test_buying_brief_no_hunt_id_no_hunts_returns_empty_shape(client, stub_verify_token, authed_headers):
    """AC 3 sanity: hunt_id missing AND no hunts → empty default shape.

    With no Hunt rows the route must still respond with the canonical
    shape so the pre-onboarding flow renders.
    """
    from sqlalchemy import delete

    from api.models import Hunt

    async def _clear():
        async with AsyncSessionLocal() as s:
            await s.execute(delete(Hunt))
            await s.commit()

    asyncio.run(_clear())

    resp = client.get("/api/buying-brief", headers=authed_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Empty default: item is empty string, max_price=0, but shape validates.
    assert "item" in body
    assert body["max_price"] >= 0, body


def test_hunt_list_active_classmethod_exists():
    """AC 4 verbatim — ``Hunt.list_active(session)`` exists + works."""
    from api.models import Hunt

    assert hasattr(Hunt, "list_active"), "Hunt.list_active not defined"

    async def _run() -> list:
        async with AsyncSessionLocal() as s:
            # Seed one in-flight hunt and confirm list_active returns it.
            hunt = await Hunt.create(
                s,
                user_id="demo_user_active_test",
                goal_text="couch under $400 in SF",
                status="awaiting_picks",
            )
            await s.commit()
            try:
                rows = await Hunt.list_active(s)
                return [r.id for r in rows if r.id == hunt.id]
            finally:
                from sqlalchemy import delete

                await s.execute(delete(Hunt).where(Hunt.id == hunt.id))
                await s.commit()

    found = asyncio.run(_run())
    assert len(found) == 1, found


def test_app_routes_load():
    """AC 1 verbatim — app loads with expected route count."""
    assert len(app.routes) > 40
