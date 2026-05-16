"""Bright Data raw -> `Listing` parser for Nextdoor.

Same defensive multi-alias pattern as `fb_marketplace.py`. Tighten field
names once the live verification pass reveals the dataset's actual keys.
"""

from __future__ import annotations

from typing import Iterable

from api.contracts import Listing
from api.integrations.bright_data._parse_utils import coerce_price_cents, first


def parse_nextdoor_listings(rows: Iterable[dict]) -> list[Listing]:
    out: list[Listing] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        listing_id = first(row, "listing_id", "id", "item_id", "post_id")
        if listing_id is None:
            continue
        out.append(
            Listing(
                marketplace="nextdoor",
                listing_id=str(listing_id),
                title=first(row, "title", "name", "headline"),
                description=first(row, "description", "body", "text"),
                price_cents=coerce_price_cents(first(row, "price", "price_usd", "amount")),
                currency=str(first(row, "currency", "price_currency") or "USD"),
                url=first(row, "url", "link", "permalink"),
                raw=row,
            )
        )
    return out
