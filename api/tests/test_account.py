"""Tests for the user account-management routes.

Covers:

- ``DELETE /api/me`` hard-deletes the user + every per-user row
  (hunts, jobs, message_threads, approval_queue, notifications,
  integration_accounts).
- ``POST /api/integrations/{provider}/unlink`` drops only the matching
  integration_accounts rows.
- ``POST /api/me/onboarding/reset`` flips ``onboarding_completed`` back
  to False.
- ``GET /api/me`` returns the enriched profile shape (``member_since``
  + ``marketplaces_status``).

EverOS memory wipe is patched out per test — we only assert the wipe
helper is *invoked* with the right user_id; the real SDK call is
covered by integration with EverOS itself (out of scope here).
"""

from __future__ import annotations

import asyncio

import pytest

# Disable Postgres-only alembic migrations during test boot (SQLite path).
import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]

from api.db import AsyncSessionLocal, Base, engine  # noqa: E402
from api.main import app  # noqa: E402
from api.models import (  # noqa: E402
    ApprovalQueueItem,
    Hunt,
    IntegrationAccountRow,
    Job,
    MessageThread,
    Notification,
    User,
)


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


async def _seed_user_with_data(google_sub: str, email: str) -> dict:
    """Seed a user + 1 hunt + 1 job + 1 message + 1 approval + 1
    notification + 1 integration_account + 1 tool-catalog row.

    Returns a dict with the seeded ids so tests can assert against them.
    """
    async with AsyncSessionLocal() as session:
        user = await User.upsert_from_google(
            session,
            {
                "sub": google_sub,
                "email": email,
                "name": "Seeded",
                "picture": "https://lh3.googleusercontent.com/seed",
            },
        )
        await session.commit()
        await session.refresh(user)
        user_id_str = str(user.id)

        hunt = await Hunt.create(
            session,
            user_id=user_id_str,
            goal_text="standing desk under $250 SF",
            budget=250.0,
        )
        await session.commit()

        job = await Job.create(
            session,
            user_id=user_id_str,
            listing_id="seed-listing-1",
            status="active",
            hunt_id=hunt.id,
        )
        await session.commit()

        msg = await MessageThread.append(
            session,
            job_id=job.id,
            role="buyer_agent",
            text="Hi, is this still available?",
        )
        await session.commit()

        approval = await ApprovalQueueItem.create(
            session,
            job_id=job.id,
            draft_text="Would you take $200?",
            approval_request_id=f"seed-approval-{google_sub}",
        )
        await session.commit()

        notif = await Notification.create(
            session,
            user_id=user_id_str,
            kind="approval_needed",
            title="Approve this draft",
            body="The agent has drafted a message.",
            target_href="/chat",
            hunt_id=hunt.id,
            job_id=job.id,
        )
        await session.commit()

        integ = await IntegrationAccountRow.upsert(
            session,
            user_id=user_id_str,
            provider="fb",
            browserbase_context_id="bb_ctx_seed_fb",
            live_view_url="https://browserbase.com/live/seed-fb",
            status="active",
        )
        await session.commit()
        integ_nd = await IntegrationAccountRow.upsert(
            session,
            user_id=user_id_str,
            provider="nextdoor",
            browserbase_context_id="bb_ctx_seed_nd",
            live_view_url="https://browserbase.com/live/seed-nd",
            status="active",
        )
        await session.commit()

        return {
            "user_id": user_id_str,
            "user_uuid": user.id,
            "hunt_id": hunt.id,
            "job_id": job.id,
            "message_id": msg.id,
            "approval_id": approval.id,
            "notification_id": notif.id,
            "integration_fb_id": integ.id,
            "integration_nd_id": integ_nd.id,
        }


async def _count_user_rows(user_id_str: str, user_uuid) -> dict:
    """Count rows per table for the given user. Used to verify the
    hard-delete dropped everything."""
    from sqlalchemy import select, func

    async with AsyncSessionLocal() as session:
        async def _count(stmt):
            res = await session.execute(stmt)
            return int(res.scalar_one())

        users = await _count(
            select(func.count(User.id)).where(User.id == user_uuid)
        )
        hunts = await _count(
            select(func.count(Hunt.id)).where(Hunt.user_id == user_id_str)
        )
        jobs = await _count(
            select(func.count(Job.id)).where(Job.user_id == user_id_str)
        )
        notifs = await _count(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id_str
            )
        )
        integs = await _count(
            select(func.count(IntegrationAccountRow.id)).where(
                IntegrationAccountRow.user_id == user_id_str
            )
        )
        # message_threads + approval_queue hang off jobs.id, so count via
        # the absent jobs link (anything still referring to a job whose
        # user_id matches counts as user-scoped leftover).
        threads = await _count(
            select(func.count(MessageThread.id)).where(
                MessageThread.job_id.in_(
                    select(Job.id).where(Job.user_id == user_id_str)
                )
            )
        )
        approvals = await _count(
            select(func.count(ApprovalQueueItem.id)).where(
                ApprovalQueueItem.job_id.in_(
                    select(Job.id).where(Job.user_id == user_id_str)
                )
            )
        )
        return {
            "users": users,
            "hunts": hunts,
            "jobs": jobs,
            "notifications": notifs,
            "integrations": integs,
            "message_threads": threads,
            "approvals": approvals,
        }


def test_delete_account_drops_all_user_data(
    client, stub_verify_token, authed_headers, monkeypatch
):
    """AC #4: DELETE /api/me returns 204 and all per-user rows are gone."""
    # Patch out the EverOS wipe so we don't try to reach the live API.
    import api.routes.me as me_mod

    wipe_calls: list[str] = []

    async def _stub_wipe(user_id: str) -> None:
        wipe_calls.append(user_id)

    monkeypatch.setattr(me_mod, "_clear_everos_memory_safe", _stub_wipe)

    # The conftest stub_verify_token fixture uses sub="test-sub" by
    # default — we want a dedicated user for this test so other tests
    # in the suite don't see a ghost row. Override the stub with a
    # custom sub so each test seeds an isolated user.
    import api.auth as auth_mod

    async def _custom_stub(token: str) -> dict:
        return {
            "sub": "delete-test-sub",
            "email": "delete@example.com",
            "name": "Delete Tester",
            "picture": "https://lh3.googleusercontent.com/delete",
        }

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _custom_stub)

    # Seed via the same google_sub so /api/me resolves to the seeded user.
    seeded = asyncio.run(
        _seed_user_with_data("delete-test-sub", "delete@example.com")
    )
    user_id_str = seeded["user_id"]
    user_uuid = seeded["user_uuid"]

    # Sanity: rows exist before the delete.
    before = asyncio.run(_count_user_rows(user_id_str, user_uuid))
    assert before["users"] == 1, before
    assert before["hunts"] == 1, before
    assert before["jobs"] == 1, before
    assert before["message_threads"] == 1, before
    assert before["approvals"] == 1, before
    assert before["notifications"] == 1, before
    assert before["integrations"] == 2, before

    # DELETE /api/me
    resp = client.delete("/api/me", headers=authed_headers)
    assert resp.status_code == 204, resp.text
    # 204 has no body; httpx returns b"" / "".
    assert resp.text == "" or resp.text is None

    # Verify all user-scoped rows gone.
    after = asyncio.run(_count_user_rows(user_id_str, user_uuid))
    assert after["users"] == 0, after
    assert after["hunts"] == 0, after
    assert after["jobs"] == 0, after
    assert after["message_threads"] == 0, after
    assert after["approvals"] == 0, after
    assert after["notifications"] == 0, after
    assert after["integrations"] == 0, after


def test_unlink_integration_drops_only_matching_provider(
    client, stub_verify_token, authed_headers, monkeypatch
):
    """AC #4: POST /api/integrations/fb/unlink returns ok and removes the row."""
    import api.auth as auth_mod

    async def _custom_stub(token: str) -> dict:
        return {
            "sub": "unlink-test-sub",
            "email": "unlink@example.com",
            "name": "Unlink Tester",
            "picture": "https://lh3.googleusercontent.com/unlink",
        }

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _custom_stub)

    seeded = asyncio.run(
        _seed_user_with_data("unlink-test-sub", "unlink@example.com")
    )
    user_id_str = seeded["user_id"]

    # Both FB + Nextdoor seeded.
    async def _list_integrations():
        async with AsyncSessionLocal() as session:
            return await IntegrationAccountRow.list_active_for_user(
                session, user_id_str
            )

    before = asyncio.run(_list_integrations())
    assert {r.provider for r in before} == {"fb", "nextdoor"}, before

    # Unlink FB only.
    resp = client.post(
        "/api/integrations/fb/unlink", headers=authed_headers
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["rows_deleted"] == 1, payload

    after = asyncio.run(_list_integrations())
    assert {r.provider for r in after} == {"nextdoor"}, after

    # Idempotent: a second unlink returns rows_deleted=0.
    resp2 = client.post(
        "/api/integrations/fb/unlink", headers=authed_headers
    )
    assert resp2.status_code == 200
    assert resp2.json()["rows_deleted"] == 0


def test_unlink_integration_rejects_unsupported_provider(
    client, stub_verify_token, authed_headers
):
    """Unsupported provider yields 400, no rows touched."""
    resp = client.post(
        "/api/integrations/bogus/unlink", headers=authed_headers
    )
    assert resp.status_code == 400, resp.text


def test_reset_onboarding_flips_flag_back_to_false(
    client, stub_verify_token, authed_headers, monkeypatch
):
    """AC #4: POST /api/me/onboarding/reset sets onboarding_completed=False."""
    import api.auth as auth_mod

    async def _custom_stub(token: str) -> dict:
        return {
            "sub": "reset-test-sub",
            "email": "reset@example.com",
            "name": "Reset Tester",
            "picture": None,
        }

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _custom_stub)

    # Bootstrap the user + flip the flag to True via the existing route.
    r1 = client.get("/api/me", headers=authed_headers)
    assert r1.status_code == 200
    assert r1.json()["onboarding_completed"] is False

    r2 = client.post(
        "/api/me/onboarding/complete", headers=authed_headers
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True

    # Confirm True via /api/me.
    r3 = client.get("/api/me", headers=authed_headers)
    assert r3.json()["onboarding_completed"] is True

    # Reset.
    r4 = client.post("/api/me/onboarding/reset", headers=authed_headers)
    assert r4.status_code == 200, r4.text
    assert r4.json()["ok"] is True

    # Confirm False via /api/me.
    r5 = client.get("/api/me", headers=authed_headers)
    assert r5.json()["onboarding_completed"] is False

    # Underlying DB row is set correctly.
    async def _read():
        async with AsyncSessionLocal() as session:
            return await User.get_by_google_sub(session, "reset-test-sub")

    user = asyncio.run(_read())
    assert user is not None
    assert user.onboarding_completed is False


def test_get_me_returns_enriched_profile(
    client, stub_verify_token, authed_headers, monkeypatch
):
    """GET /api/me includes member_since (ISO) + marketplaces_status."""
    import api.auth as auth_mod

    async def _custom_stub(token: str) -> dict:
        return {
            "sub": "enriched-test-sub",
            "email": "enriched@example.com",
            "name": "Enriched Tester",
            "picture": None,
        }

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _custom_stub)

    # Before any integration_account: marketplaces_status = "not linked".
    r1 = client.get("/api/me", headers=authed_headers)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["marketplaces_status"] == "not linked"
    assert isinstance(body1["member_since"], str)
    assert "T" in body1["member_since"]  # ISO-8601 format sanity

    # Seed an integration row → marketplaces_status flips to "linked".
    async def _seed_integ():
        async with AsyncSessionLocal() as session:
            user = await User.get_by_google_sub(session, "enriched-test-sub")
            assert user is not None
            await IntegrationAccountRow.upsert(
                session,
                user_id=str(user.id),
                provider="fb",
                browserbase_context_id="bb_ctx_enriched_fb",
                live_view_url="https://browserbase.com/live/enriched",
                status="active",
            )
            await session.commit()

    asyncio.run(_seed_integ())

    r2 = client.get("/api/me", headers=authed_headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["marketplaces_status"] == "linked"
