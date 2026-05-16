"""Deterministic Bright Data mock — `Listing[]` fixtures.

The returned listings match the SPEC.md `Listing` Pydantic shape (see
``api/contracts.py::Listing``). Prices cluster around $200-$300 to simulate
the standing-desk demo flow. Stream C will reconcile the real
`api/integrations/discovery.py` against this mock at convergence — they
share the same ``search(query, marketplaces, max_per_source)`` signature
per the SPEC.md B<->C contract.
"""

from __future__ import annotations

from api.contracts import Listing


def search(
    query: str,  # noqa: ARG001 — fixtures ignore query semantics; demo-flow testability
    marketplaces: list[str] | None = None,
    max_per_source: int = 10,
) -> list[Listing]:
    """Return ~5 fixture listings.

    Ignores query semantics by design so demo-day variations of the goal
    text still produce a populated discovery view. Filter by `marketplaces`
    if provided; otherwise returns the full fixture set capped at
    `max_per_source`.
    """
    base = [
        Listing(
            id="lst-mock-1",
            title="Adjustable standing desk, walnut top",
            price=215.0,
            marketplace="fb",
            url="https://facebook.com/marketplace/item/mock-1",
            image_url="https://placehold.co/600x400?text=Standing+Desk",
            seller_name="Maya R.",
            location="Mission District, SF",
            description="Electric height-adjust, used 6 months. Pickup only.",
        ),
        Listing(
            id="lst-mock-2",
            title="Uplift V2 standing desk (gently used)",
            price=240.0,
            marketplace="nextdoor",
            url="https://nextdoor.com/for_sale/mock-2",
            image_url="https://placehold.co/600x400?text=Uplift+Desk",
            seller_name="Diego M.",
            location="SoMa, SF",
            description="Bought new in 2024. Moving sale.",
        ),
        Listing(
            id="lst-mock-3",
            title="FlexiSpot E7 frame + bamboo top",
            price=199.0,
            marketplace="offerup",
            url="https://offerup.com/item/mock-3",
            image_url="https://placehold.co/600x400?text=FlexiSpot",
            seller_name="Priya S.",
            location="Inner Sunset, SF",
            description="Frame in great shape; small scratch on top.",
        ),
        Listing(
            id="lst-mock-4",
            title="Vivo standing desk converter",
            price=125.0,
            marketplace="craigslist",
            url="https://craigslist.org/item/mock-4",
            image_url="https://placehold.co/600x400?text=Vivo",
            seller_name="Mike K.",
            location="Oakland",
            description="Sits on existing desk. Like new.",
        ),
        Listing(
            id="lst-mock-5",
            title="Autonomous SmartDesk 2",
            price=285.0,
            marketplace="fb",
            url="https://facebook.com/marketplace/item/mock-5",
            image_url="https://placehold.co/600x400?text=Autonomous",
            seller_name="Jasmine T.",
            location="Berkeley",
            description="Black frame, white top. 2 yr warranty.",
        ),
    ]
    if marketplaces:
        base = [listing for listing in base if listing.marketplace in marketplaces]
    return base[:max_per_source]
