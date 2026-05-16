"""Bright Data Web Scraper API client (sync mode).

Round-1 scope: a single FB Marketplace dataset wired end-to-end. Other
marketplaces raise `NotImplementedError` so the discovery dispatcher can skip
them without falsely returning empty results.

Auth: `Authorization: Bearer ${BRIGHT_DATA_API_KEY}` per Bright Data docs.

Endpoint shape (sync mode): POST to the trigger endpoint with `dataset_id`
in the query string + the scraper inputs in the JSON body. Sync mode blocks
until results are ready and returns the rows directly. The exact endpoint
URL is the Web Scraper API v3 trigger route; verify against Bright Data's
"Web Scraper API → Trigger via API" docs page before first live run.
"""

from __future__ import annotations

import httpx

from api.contracts import Listing
from api.integrations.bright_data.fb_marketplace import parse_fb_listings
from api.settings import settings

# Bright Data Web Scraper API — sync-mode trigger endpoint.
# Form per Bright Data docs: POST {BASE}?dataset_id=...&format=json&include_errors=true
# Body: list[dict] of per-row inputs. Sync mode (this URL) waits for results.
# TODO(dev): confirm the exact endpoint URL + payload field names from
# Bright Data's current "Web Scraper API → Trigger via API (sync)" docs the
# first time you run the live test. Common alternates: /datasets/v3/scrape
# (sync) vs /datasets/v3/trigger (async). Adjust here if needed.
BRIGHT_DATA_BASE = "https://api.brightdata.com"
BRIGHT_DATA_SYNC_TRIGGER = f"{BRIGHT_DATA_BASE}/datasets/v3/scrape"

# Marketplace -> dataset-ID env var. Only `fb` is wired this round.
_DATASET_ENV = {
    "fb": "bright_data_fb_dataset_id",
}

_TIMEOUT = httpx.Timeout(30.0)


def _dataset_id_for(marketplace: str) -> str:
    attr = _DATASET_ENV.get(marketplace)
    if attr is None:
        raise NotImplementedError(
            f"Bright Data marketplace '{marketplace}' not wired this round; "
            "only 'fb' is configured. Add a dataset ID + parser to enable it."
        )
    dataset_id = getattr(settings, attr, None)
    if not dataset_id:
        raise RuntimeError(
            f"Missing dataset ID for marketplace '{marketplace}'. "
            f"Set BRIGHT_DATA_FB_DATASET_ID in your env "
            f"(run `python -m api.integrations.bright_data.discover_datasets` "
            f"to list options)."
        )
    return dataset_id


def _auth_headers() -> dict[str, str]:
    api_key = settings.bright_data_api_key
    if not api_key:
        raise RuntimeError(
            "BRIGHT_DATA_API_KEY is not set. Live calls require a Bright Data "
            "API key (or run with GOTI_USE_MOCKS=1 for the mock path)."
        )
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def fetch_listings(
    marketplace: str,
    query: str,
    max_per_source: int = 10,
) -> list[Listing]:
    """Fetch listings for `marketplace` matching `query` via Bright Data sync mode.

    Returns a list of `Listing` parsed via the per-marketplace parser.
    Raises NotImplementedError for unwired marketplaces (caller may skip).
    """
    if marketplace != "fb":
        raise NotImplementedError(
            f"Only 'fb' is wired this round; got '{marketplace}'."
        )

    dataset_id = _dataset_id_for(marketplace)
    # FB Marketplace scraper input shape varies by dataset. A typical
    # search-by-keyword dataset expects {"keyword": ..., "country": ...}.
    # TODO(dev): confirm the exact input keys by inspecting the dataset
    # schema in Bright Data's dashboard (or via `discover_datasets.py`).
    payload = [{"keyword": query, "country": "US"}]
    params = {
        "dataset_id": dataset_id,
        "format": "json",
        "include_errors": "true",
        "limit_per_input": str(max_per_source),
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            BRIGHT_DATA_SYNC_TRIGGER,
            headers=_auth_headers(),
            params=params,
            json=payload,
        )
        resp.raise_for_status()
        raw = resp.json()

    # Sync mode returns either a list of rows directly, or a wrapper dict
    # with the rows under a key like "data"/"records". Normalise both.
    if isinstance(raw, dict):
        rows = raw.get("data") or raw.get("records") or raw.get("results") or []
    else:
        rows = raw
    if not isinstance(rows, list):
        rows = []

    return parse_fb_listings(rows)[:max_per_source]
