"""Mock-path tests for `api.integrations.discovery.search`.

These run by default (no marker). They verify:
1. The mock dispatch is hit when `use_mocks=True`.
2. The mock returns the expected shape + count.
3. The query reaches the mock (echoed into title).
4. Unwired marketplaces return zero rows from the mock, not an error.
"""

from __future__ import annotations

import pytest

from api.contracts import Listing
from api.integrations import discovery


@pytest.mark.asyncio
async def test_mock_returns_three_fb_listings(use_mocks):
    results = await discovery.search("standing desk", ["fb"], max_per_source=10)
    assert len(results) == 3
    for r in results:
        assert isinstance(r, Listing)
        assert r.marketplace == "fb"
        assert r.listing_id.startswith("fb_mock_")
        assert "standing desk" in (r.title or "").lower()
        assert r.price_cents is not None and r.price_cents > 0


@pytest.mark.asyncio
async def test_mock_respects_max_per_source(use_mocks):
    results = await discovery.search("anything", ["fb"], max_per_source=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_mock_skips_unwired_marketplaces(use_mocks):
    # Asking for fb + an unwired marketplace returns only the 3 fb rows;
    # the unwired-marketplace mock is empty (Round 3: all 4 supported
    # marketplaces are wired, so we use a deliberately bogus name here).
    results = await discovery.search("desk", ["fb", "amazon"], max_per_source=10)
    assert len(results) == 3
    assert all(r.marketplace == "fb" for r in results)


@pytest.mark.asyncio
async def test_mock_returns_all_four_marketplaces(use_mocks):
    """Round 3: fb + nextdoor + offerup + craigslist all return rows when
    requested together. Verifies sponsor depth (≥3 marketplaces) end-to-end
    on the mock path."""
    listings = await discovery.search(
        "desk",
        ["fb", "nextdoor", "offerup", "craigslist"],
        max_per_source=5,
    )
    found = {l.marketplace for l in listings}
    assert {"fb", "nextdoor", "offerup", "craigslist"}.issubset(found)
    # Each marketplace fixture set is 3 rows; total should be 12.
    assert len(listings) == 12
    for l in listings:
        assert isinstance(l, Listing)
        assert "desk" in (l.title or "").lower()


@pytest.mark.asyncio
async def test_real_path_not_invoked_when_use_mocks(monkeypatch, use_mocks):
    """Guard: when use_mocks=True, the Bright Data client must not be called."""
    from api.integrations.bright_data import client as bd_client

    called = {"n": 0}

    async def _boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("real fetch_listings should not be called under mocks")

    monkeypatch.setattr(bd_client, "fetch_listings", _boom)
    results = await discovery.search("desk", ["fb"], max_per_source=10)
    assert len(results) == 3
    assert called["n"] == 0
