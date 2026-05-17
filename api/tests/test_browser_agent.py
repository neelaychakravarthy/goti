"""Unit tests for ``api.integrations.browser_agent.actions``.

The actions module is the canonical seam between the lifecycle code
and the LLM-driven browser agent. These tests pin its behaviour by
monkeypatching the low-level ``client.run_action`` (which would
otherwise spawn a Browserbase session + run a real LLM agent), and
asserting that:

- ``search_listings`` parses well-formed JSON output into ``Listing[]``;
- ``send_message`` synthesizes a stable ``MessageId``;
- ``fetch_replies`` parses well-formed JSON output into ``Reply[]``;
- malformed / non-JSON output degrades gracefully (empty list, flagged
  ``MessageId``) rather than raising.
"""

from __future__ import annotations

import pytest

from api.contracts import Listing, MessageId, Reply
from api.integrations.browser_agent import actions, client


# ---------------------------------------------------------------------------
# search_listings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_listings_parses_json_array(monkeypatch):
    """Agent returns a JSON array of listings → ``Listing[]`` validated."""

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return [
            {
                "id": "fb-listing-1",
                "title": "Standing desk — Uplift",
                "price": 220,
                "marketplace": "fb",
                "url": "https://facebook.com/marketplace/item/fb-listing-1",
                "image_url": None,
                "seller_name": "Daniel",
                "location": "SF",
                "description": "Excellent condition.",
            },
            {
                "id": "nd-listing-2",
                "title": "FlexiSpot E7",
                "price": 195,
                "marketplace": "nextdoor",
                "url": "https://nextdoor.com/listing/nd-listing-2",
                "image_url": None,
                "seller_name": "Ari",
                "location": "Sunset",
                "description": None,
            },
        ]

    monkeypatch.setattr(client, "run_action", _stub)
    out = await actions.search_listings(
        context_id="bb_ctx_test",
        query="standing desk",
        marketplaces=["fb", "nextdoor"],
        max_per_source=5,
    )
    assert len(out) == 2
    assert all(isinstance(li, Listing) for li in out)
    assert {li.marketplace for li in out} == {"fb", "nextdoor"}
    assert out[0].id == "fb-listing-1"
    assert out[1].price == 195


@pytest.mark.asyncio
async def test_search_listings_skips_malformed_entries(monkeypatch):
    """A single broken row doesn't drop the whole result set."""

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return [
            {
                "id": "fb-listing-1",
                "title": "Valid",
                "price": 220,
                "marketplace": "fb",
                "url": "https://facebook.com/marketplace/item/fb-listing-1",
            },
            {"id": "missing-fields"},  # invalid — no title/price/marketplace/url
            "not-even-a-dict",
        ]

    monkeypatch.setattr(client, "run_action", _stub)
    out = await actions.search_listings(
        context_id="bb_ctx_test",
        query="desk",
        marketplaces=["fb"],
        max_per_source=5,
    )
    assert len(out) == 1
    assert out[0].id == "fb-listing-1"


@pytest.mark.asyncio
async def test_search_listings_accepts_wrapped_dict(monkeypatch):
    """Agent wraps the array in {"listings": [...]} → still parsed."""

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return {
            "listings": [
                {
                    "id": "fb-listing-1",
                    "title": "Wrapped",
                    "price": 100,
                    "marketplace": "fb",
                    "url": "https://facebook.com/marketplace/item/fb-listing-1",
                }
            ]
        }

    monkeypatch.setattr(client, "run_action", _stub)
    out = await actions.search_listings(
        context_id="bb_ctx_test",
        query="x",
        marketplaces=["fb"],
    )
    assert len(out) == 1
    assert out[0].title == "Wrapped"


@pytest.mark.asyncio
async def test_search_listings_empty_marketplaces_short_circuits(monkeypatch):
    """No supported marketplaces → return [] without invoking the agent."""

    calls: list[str] = []

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        calls.append(context_id)
        return []

    monkeypatch.setattr(client, "run_action", _stub)
    out = await actions.search_listings(
        context_id="bb_ctx_test",
        query="x",
        marketplaces=["amazon"],
    )
    assert out == []
    assert calls == [], "agent should not be invoked when no targets are valid"


@pytest.mark.asyncio
async def test_search_listings_swallows_agent_errors(monkeypatch):
    """Agent raises → ``search_listings`` returns [] instead of bubbling."""

    async def _boom(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        raise RuntimeError("agent timed out")

    monkeypatch.setattr(client, "run_action", _boom)
    out = await actions.search_listings(
        context_id="bb_ctx_test",
        query="x",
        marketplaces=["fb"],
    )
    assert out == []


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_synthesizes_message_id(monkeypatch):
    """Successful agent run → ``MessageId`` with the marketplace tag."""

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return {"sent": True, "error": None}

    monkeypatch.setattr(client, "run_action", _stub)
    msg_id = await actions.send_message(
        context_id="bb_ctx_test",
        listing_url="https://facebook.com/marketplace/item/fb-1",
        listing_id="fb-1",
        message_text="Hi — still available?",
        marketplace="fb",
    )
    assert isinstance(msg_id, str)
    assert msg_id.startswith("bb-fb-fb-1-")


@pytest.mark.asyncio
async def test_send_message_returns_id_even_on_unconfirmed(monkeypatch):
    """Agent reports ``sent: false`` → still mint an id, but log the warning.

    We don't surface a typed error here — the upstream callers treat a
    ``MessageId`` as "we tried" and rely on subsequent reply polling +
    user-visible job state to detect failure.
    """

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return {"sent": False, "error": "no send button found"}

    monkeypatch.setattr(client, "run_action", _stub)
    msg_id = await actions.send_message(
        context_id="bb_ctx_test",
        listing_url="https://facebook.com/marketplace/item/fb-1",
        listing_id="fb-1",
        message_text="text",
        marketplace="fb",
    )
    assert isinstance(msg_id, str)
    assert msg_id.startswith("bb-fb-fb-1-")


@pytest.mark.asyncio
async def test_send_message_swallows_agent_errors(monkeypatch):
    """Agent raises → return a flagged ``-err`` id; never bubble."""

    async def _boom(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        raise RuntimeError("Browserbase 502")

    monkeypatch.setattr(client, "run_action", _boom)
    msg_id = await actions.send_message(
        context_id="bb_ctx_test",
        listing_url="https://nextdoor.com/listing/nd-1",
        listing_id="nd-1",
        message_text="text",
        marketplace="nextdoor",
    )
    assert msg_id == "bb-nextdoor-nd-1-err"


# ---------------------------------------------------------------------------
# fetch_replies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_replies_parses_json_array(monkeypatch):
    """Agent returns a JSON array of replies → ``Reply[]``."""

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return [
            {"text": "Still available — $230 firm.", "sent_at": 1700000000.0},
            {"text": "Can pick up tomorrow?", "sent_at": 1700000100.0},
        ]

    monkeypatch.setattr(client, "run_action", _stub)
    replies = await actions.fetch_replies(
        context_id="bb_ctx_test",
        listing_url="https://facebook.com/marketplace/item/fb-1",
        listing_id="fb-1",
        marketplace="fb",
        since_ts=1699999000.0,
    )
    assert len(replies) == 2
    assert all(isinstance(r, Reply) for r in replies)
    assert replies[0].text.startswith("Still available")
    assert replies[0].sender == "seller"
    assert replies[0].listing_id == "fb-1"
    assert replies[0].received_at == 1700000000.0
    assert replies[1].received_at == 1700000100.0


@pytest.mark.asyncio
async def test_fetch_replies_empty_array(monkeypatch):
    """Agent returns [] → ``fetch_replies`` returns []."""

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return []

    monkeypatch.setattr(client, "run_action", _stub)
    replies = await actions.fetch_replies(
        context_id="bb_ctx_test",
        listing_url="https://facebook.com/marketplace/item/fb-1",
        listing_id="fb-1",
        marketplace="fb",
        since_ts=1699999000.0,
    )
    assert replies == []


@pytest.mark.asyncio
async def test_fetch_replies_skips_empty_text(monkeypatch):
    """A reply with no text is silently dropped."""

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return [
            {"text": "", "sent_at": 1700000000.0},
            {"text": "Real reply.", "sent_at": 1700000100.0},
        ]

    monkeypatch.setattr(client, "run_action", _stub)
    replies = await actions.fetch_replies(
        context_id="bb_ctx_test",
        listing_url="https://facebook.com/marketplace/item/fb-1",
        listing_id="fb-1",
        marketplace="fb",
        since_ts=1699999000.0,
    )
    assert len(replies) == 1
    assert replies[0].text == "Real reply."


@pytest.mark.asyncio
async def test_fetch_replies_accepts_wrapped_dict(monkeypatch):
    """Agent wraps the array in {"messages": [...]} → still parsed."""

    async def _stub(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        return {
            "messages": [
                {"text": "Hi", "sent_at": 1700000000.0},
            ]
        }

    monkeypatch.setattr(client, "run_action", _stub)
    replies = await actions.fetch_replies(
        context_id="bb_ctx_test",
        listing_url="https://nextdoor.com/listing/nd-1",
        listing_id="nd-1",
        marketplace="nextdoor",
        since_ts=1699999000.0,
    )
    assert len(replies) == 1
    assert replies[0].message_id.startswith("bb-nextdoor-reply-nd-1-")


@pytest.mark.asyncio
async def test_fetch_replies_swallows_agent_errors(monkeypatch):
    """Agent raises → ``fetch_replies`` returns []."""

    async def _boom(context_id: str, task: str, *, max_steps: int = 25, **kwargs):
        raise RuntimeError("Browserbase 503")

    monkeypatch.setattr(client, "run_action", _boom)
    replies = await actions.fetch_replies(
        context_id="bb_ctx_test",
        listing_url="https://facebook.com/marketplace/item/fb-1",
        listing_id="fb-1",
        marketplace="fb",
        since_ts=1699999000.0,
    )
    assert replies == []


# ---------------------------------------------------------------------------
# client.run_action shape sanity
# ---------------------------------------------------------------------------


def test_run_action_is_callable():
    """AC #3 — ``client.run_action`` is callable (smoke import test)."""
    assert callable(client.run_action)


def test_actions_are_callable():
    """AC #3 — high-level actions are exposed + callable."""
    assert callable(actions.search_listings)
    assert callable(actions.send_message)
    assert callable(actions.fetch_replies)


def test_browser_agent_error_is_importable():
    """``BrowserAgentError`` is the canonical exception for caller catches."""
    assert issubclass(client.BrowserAgentError, RuntimeError)
