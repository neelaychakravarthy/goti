"""Tests for the Browserbase integration + browser-agent surface.

Covers the link / finish / unlink integration routes plus a sanity
check that the browser-agent's action surface drives the stubbed
Browserbase client. The Browserbase SDK + browser-use runtime are both
stubbed via the ``stub_browserbase`` fixture so these tests run with no
API key + no Chromium binary.
"""

from __future__ import annotations

import asyncio

import pytest


# Disable Postgres-only alembic migrations during test boot (SQLite path).
import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]

from api.db import Base, engine  # noqa: E402
from api.integrations.browser_agent import actions as agent_actions  # noqa: E402
from api.integrations.browserbase import client as bb_client  # noqa: E402
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


# ---------------------------------------------------------------------------
# Driver-level send_message / fetch_replies (stubbed by the fixture)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fb_send_message_returns_message_id(stub_browserbase):
    msg_id = await agent_actions.send_message(
        context_id="bb_ctx_test",
        listing_url="https://facebook.com/marketplace/item/listing-456",
        listing_id="listing-456",
        message_text="Hello!",
        marketplace="fb",
    )
    assert msg_id.startswith("stub-fb-msg-")


@pytest.mark.asyncio
async def test_nextdoor_send_message_returns_message_id(stub_browserbase):
    msg_id = await agent_actions.send_message(
        context_id="bb_ctx_test",
        listing_url="https://nextdoor.com/listing/listing-456",
        listing_id="listing-456",
        message_text="Hi",
        marketplace="nextdoor",
    )
    assert msg_id.startswith("stub-nextdoor-msg-")


@pytest.mark.asyncio
async def test_fb_fetch_replies_returns_empty_for_no_replies(stub_browserbase):
    replies = await agent_actions.fetch_replies(
        context_id="bb_ctx_test",
        listing_url="https://facebook.com/marketplace/item/listing-456",
        listing_id="listing-456",
        marketplace="fb",
        since_ts=0.0,
    )
    assert replies == []


@pytest.mark.asyncio
async def test_nextdoor_fetch_replies_returns_empty_for_no_replies(stub_browserbase):
    replies = await agent_actions.fetch_replies(
        context_id="bb_ctx_test",
        listing_url="https://nextdoor.com/listing/listing-456",
        listing_id="listing-456",
        marketplace="nextdoor",
        since_ts=0.0,
    )
    assert replies == []


# ---------------------------------------------------------------------------
# Client-surface presence — guards against accidental rename in client.py
# ---------------------------------------------------------------------------


def test_browserbase_client_surface_complete():
    """The Browserbase SDK wrapper exports the verbs the routes call."""
    assert hasattr(bb_client, "create_context")
    assert hasattr(bb_client, "create_session_with_live_view")
    assert hasattr(bb_client, "create_headless_session")
    assert hasattr(bb_client, "end_session")
    assert hasattr(bb_client, "delete_context")


def test_browser_agent_surface_complete():
    """The browser-agent's high-level actions are exposed."""
    assert hasattr(agent_actions, "search_listings")
    assert hasattr(agent_actions, "send_message")
    assert hasattr(agent_actions, "fetch_replies")


# ---------------------------------------------------------------------------
# Integration routes: link → finish → unlink (DB-backed via SQLite + stubs)
# ---------------------------------------------------------------------------


def test_link_finish_unlink_flow(
    client, stub_verify_token, stub_browserbase, authed_headers, monkeypatch
):
    """End-to-end happy path on the link / finish / unlink lifecycle.

    Uses a dedicated user (custom sub stub) so the row is isolated from
    other tests in the suite.
    """
    import api.auth as auth_mod

    async def _custom_stub(token: str) -> dict:
        return {
            "sub": "bb-link-test-sub",
            "email": "bb-link@example.com",
            "name": "BB Link Tester",
            "picture": None,
        }

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _custom_stub)

    # ---- /link returns the stubbed live-view URL + creates pending row ----
    resp = client.post(
        "/api/integrations/fb/link",
        headers=authed_headers,
        json={},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["authorize_url"] == "https://browserbase.com/live/test"
    assert body["state"] == "bb_ctx_test"
    assert body["provider"] == "fb"

    # ---- /finish flips status=active ----
    resp = client.post(
        "/api/integrations/fb/finish",
        headers=authed_headers,
        json={},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "validated": True}

    # ---- /api/integrations reports linked=True for fb ----
    resp = client.get("/api/integrations", headers=authed_headers)
    assert resp.status_code == 200, resp.text
    integrations = resp.json()
    fb_row = next(r for r in integrations if r["provider"] == "fb")
    assert fb_row["linked"] is True

    # ---- /unlink deletes the row ----
    resp = client.post(
        "/api/integrations/fb/unlink",
        headers=authed_headers,
        json={},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["rows_deleted"] == 1

    # Re-check — fb is no longer linked.
    resp = client.get("/api/integrations", headers=authed_headers)
    integrations = resp.json()
    fb_row = next(r for r in integrations if r["provider"] == "fb")
    assert fb_row["linked"] is False
