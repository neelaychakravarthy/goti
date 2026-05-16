"""Deterministic mock for `api.integrations.discovery.search`.

Same async signature as the real one. Returns 3 hardcoded `Listing` rows
per supported marketplace (FB / Nextdoor / OfferUp / Craigslist as of
round 3), with the query echoed into the title so test assertions can
verify the query reached the mock.

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

_NEXTDOOR_FIXTURES: list[dict] = [
    {
        "listing_id": "nd_mock_0001",
        "title_base": "Used neighborhood pickup",
        "description": "Light wear, available this weekend. Cash only.",
        "price_cents": 27500,
        "url": "https://nextdoor.com/for_sale/nd_mock_0001",
    },
    {
        "listing_id": "nd_mock_0002",
        "title_base": "Barely used - $250 OBO",
        "description": "Moving out of the neighborhood, must sell. Pickup in Mission.",
        "price_cents": 25000,
        "url": "https://nextdoor.com/for_sale/nd_mock_0002",
    },
    {
        "listing_id": "nd_mock_0003",
        "title_base": "Free for pickup this weekend",
        "description": "Free to a good home. First come first served.",
        "price_cents": 0,
        "url": "https://nextdoor.com/for_sale/nd_mock_0003",
    },
]

_OFFERUP_FIXTURES: list[dict] = [
    {
        "listing_id": "ou_mock_0001",
        "title_base": "OfferUp local deal",
        "description": "Great condition, smoke-free home. Meet at the park.",
        "price_cents": 19500,
        "url": "https://offerup.com/item/detail/ou_mock_0001",
    },
    {
        "listing_id": "ou_mock_0002",
        "title_base": "Negotiable - shipping ok",
        "description": "Open to offers. Can ship within CA.",
        "price_cents": 24000,
        "url": "https://offerup.com/item/detail/ou_mock_0002",
    },
    {
        "listing_id": "ou_mock_0003",
        "title_base": "Brand new in box",
        "description": "Never opened. Got as a gift, not my style.",
        "price_cents": 31000,
        "url": "https://offerup.com/item/detail/ou_mock_0003",
    },
]

_CRAIGSLIST_FIXTURES: list[dict] = [
    {
        "listing_id": "cl_mock_0001",
        "title_base": "SF Bay - must go this week",
        "description": "Moving, everything must go. SOMA pickup only.",
        "price_cents": 15000,
        "url": "https://sfbay.craigslist.org/sfc/fuo/d/cl_mock_0001.html",
    },
    {
        "listing_id": "cl_mock_0002",
        "title_base": "Great condition - $200 firm",
        "description": "Used for 6 months. No low-ballers please.",
        "price_cents": 20000,
        "url": "https://sfbay.craigslist.org/sfc/fuo/d/cl_mock_0002.html",
    },
    {
        "listing_id": "cl_mock_0003",
        "title_base": "Quick sale - cash only",
        "description": "Need gone by Sunday. Berkeley pickup.",
        "price_cents": 12500,
        "url": "https://sfbay.craigslist.org/eby/fuo/d/cl_mock_0003.html",
    },
]

# Marketplace -> fixture list. Unwired marketplaces return [] (mirror the
# real client's "skip silently" semantics for unwired markets).
_FIXTURES_BY_MARKETPLACE: dict[str, list[dict]] = {
    "fb": _FB_FIXTURES,
    "nextdoor": _NEXTDOOR_FIXTURES,
    "offerup": _OFFERUP_FIXTURES,
    "craigslist": _CRAIGSLIST_FIXTURES,
}


def _fixture_for(marketplace: str, query: str, max_per_source: int) -> list[Listing]:
    fixtures = _FIXTURES_BY_MARKETPLACE.get(marketplace)
    if not fixtures:
        return []
    out: list[Listing] = []
    for fx in fixtures[:max_per_source]:
        out.append(
            Listing(
                marketplace=marketplace,
                listing_id=fx["listing_id"],
                title=f"{fx['title_base']} — re: {query}",
                description=fx["description"],
                price_cents=fx["price_cents"],
                currency="USD",
                url=fx["url"],
                raw={"mock": True, "query": query, "marketplace": marketplace, **fx},
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
