"""Deterministic mock for `api.integrations.discovery.search`.

Same async signature as the real one. Returns 3 hardcoded `Listing` rows
per supported marketplace (currently only `fb`), with the query echoed into
the title so test assertions can verify the query reached the mock.

Used by Streams A + B for offline dev under `GOTI_USE_MOCKS=1`.
"""

from __future__ import annotations

from api.contracts import Listing

# Base fixtures — title is suffixed with the query at call time so mocked
# results look query-relevant to downstream agents + UI cards.
_FB_FIXTURES: list[dict] = [
    {
        "listing_id": "fb_mock_0001",
        "title_base": "Standing Desk - Like New",
        "description": "Adjustable height standing desk, used for 3 months. Walnut top.",
        "price_cents": 22500,
        "url": "https://facebook.com/marketplace/item/fb_mock_0001",
    },
    {
        "listing_id": "fb_mock_0002",
        "title_base": "Sit/Stand Desk (Black)",
        "description": "Electric sit/stand desk, 60x30. Slight scratches on rear edge.",
        "price_cents": 18000,
        "url": "https://facebook.com/marketplace/item/fb_mock_0002",
    },
    {
        "listing_id": "fb_mock_0003",
        "title_base": "Vintage Mid-Century Desk",
        "description": "Solid teak, 1960s. Not adjustable — but beautiful.",
        "price_cents": 32500,
        "url": "https://facebook.com/marketplace/item/fb_mock_0003",
    },
]


def _fixture_for(marketplace: str, query: str, max_per_source: int) -> list[Listing]:
    if marketplace != "fb":
        # Mirror the real client's "skip silently" semantics for unwired markets.
        return []
    out: list[Listing] = []
    for fx in _FB_FIXTURES[:max_per_source]:
        out.append(
            Listing(
                marketplace="fb",
                listing_id=fx["listing_id"],
                title=f"{fx['title_base']} — re: {query}",
                description=fx["description"],
                price_cents=fx["price_cents"],
                currency="USD",
                url=fx["url"],
                raw={"mock": True, "query": query, **fx},
            )
        )
    return out


async def search(
    query: str,
    marketplaces: list[str],
    max_per_source: int = 10,
) -> list[Listing]:
    out: list[Listing] = []
    for mp in marketplaces:
        out.extend(_fixture_for(mp, query, max_per_source))
    return out
