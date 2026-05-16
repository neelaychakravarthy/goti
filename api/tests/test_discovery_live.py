"""Live Bright Data smoke test.

Skipped by default. Run via:

    cd api
    source .venv/bin/activate
    export BRIGHT_DATA_API_KEY=...
    export BRIGHT_DATA_FB_DATASET_ID=...   # from discover_datasets.py
    pytest -m live -k test_discovery_live

One real HTTP call. Burns Bright Data credits — do not enable in CI.
"""

from __future__ import annotations

import os

import pytest

from api.contracts import Listing
from api.integrations import discovery


def _reload_settings_no_mocks() -> None:
    """Drop the cached Settings singleton so the next `get_settings()` re-reads
    env vars set in the calling shell, then force `use_mocks=False`."""
    from api.config import get_settings

    get_settings.cache_clear()
    fresh = get_settings()
    fresh.use_mocks = False


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_bright_data_fb_returns_listings(no_mocks):
    if not os.environ.get("BRIGHT_DATA_API_KEY"):
        pytest.skip("BRIGHT_DATA_API_KEY not set")
    if not os.environ.get("BRIGHT_DATA_FB_DATASET_ID"):
        pytest.skip(
            "BRIGHT_DATA_FB_DATASET_ID not set "
            "(run `python -m api.integrations.bright_data.discover_datasets`)"
        )

    _reload_settings_no_mocks()

    results = await discovery.search("standing desk", ["fb"], max_per_source=3)
    assert isinstance(results, list)
    assert len(results) >= 1
    assert all(isinstance(r, Listing) for r in results)
    assert all(r.marketplace == "fb" for r in results)


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_bright_data_nextdoor_returns_listings(no_mocks):
    if not os.environ.get("BRIGHT_DATA_API_KEY"):
        pytest.skip("BRIGHT_DATA_API_KEY not set")
    if not os.environ.get("BRIGHT_DATA_NEXTDOOR_DATASET_ID"):
        pytest.skip(
            "BRIGHT_DATA_NEXTDOOR_DATASET_ID not set "
            "(run `python -m api.integrations.bright_data.discover_datasets`)"
        )

    _reload_settings_no_mocks()

    results = await discovery.search("couch", ["nextdoor"], max_per_source=3)
    assert isinstance(results, list)
    assert len(results) >= 1
    assert all(isinstance(r, Listing) for r in results)
    assert all(r.marketplace == "nextdoor" for r in results)


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_bright_data_offerup_returns_listings(no_mocks):
    if not os.environ.get("BRIGHT_DATA_API_KEY"):
        pytest.skip("BRIGHT_DATA_API_KEY not set")
    if not os.environ.get("BRIGHT_DATA_OFFERUP_DATASET_ID"):
        pytest.skip(
            "BRIGHT_DATA_OFFERUP_DATASET_ID not set "
            "(run `python -m api.integrations.bright_data.discover_datasets`)"
        )

    _reload_settings_no_mocks()

    results = await discovery.search("bicycle", ["offerup"], max_per_source=3)
    assert isinstance(results, list)
    assert len(results) >= 1
    assert all(isinstance(r, Listing) for r in results)
    assert all(r.marketplace == "offerup" for r in results)


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_bright_data_craigslist_returns_listings(no_mocks):
    if not os.environ.get("BRIGHT_DATA_API_KEY"):
        pytest.skip("BRIGHT_DATA_API_KEY not set")
    if not os.environ.get("BRIGHT_DATA_CRAIGSLIST_DATASET_ID"):
        pytest.skip(
            "BRIGHT_DATA_CRAIGSLIST_DATASET_ID not set "
            "(run `python -m api.integrations.bright_data.discover_datasets`)"
        )

    _reload_settings_no_mocks()

    results = await discovery.search("monitor", ["craigslist"], max_per_source=3)
    assert isinstance(results, list)
    assert len(results) >= 1
    assert all(isinstance(r, Listing) for r in results)
    assert all(r.marketplace == "craigslist" for r in results)
