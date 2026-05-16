"""Bright Data raw -> `Listing` parser for FB Marketplace.

Bright Data's FB Marketplace dataset rows vary in shape between collectors.
This parser is defensive: it pulls the common fields when present and stuffs
the entire raw row into `Listing.raw` so downstream consumers can recover
anything we missed.

TODO(dev): once the team picks the canonical FB Marketplace dataset and
runs it once, tighten the field mapping here against the real row keys.
"""

from __future__ import annotations

from typing import Any, Iterable

from api.contracts import Listing


def _coerce_price_cents(raw_price: Any) -> int | None:
    """Best-effort price -> integer cents.

    Bright Data datasets sometimes return price as a number, sometimes as a
    string like "$249" or "249.00 USD". Strip non-numeric, parse as float,
    multiply by 100. Return None if we can't make sense of it.
    """
    if raw_price is None:
        return None
    if isinstance(raw_price, (int, float)):
        return int(round(float(raw_price) * 100))
    if isinstance(raw_price, str):
        cleaned = "".join(ch for ch in raw_price if ch.isdigit() or ch == ".")
        if not cleaned:
            return None
        try:
            return int(round(float(cleaned) * 100))
        except ValueError:
            return None
    return None


def _first(row: dict, *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def parse_fb_listings(rows: Iterable[dict]) -> list[Listing]:
    out: list[Listing] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        listing_id = _first(row, "listing_id", "id", "item_id", "marketplace_listing_id")
        if listing_id is None:
            # Skip rows without an id; nothing useful we can do.
            continue
        out.append(
            Listing(
                marketplace="fb",
                listing_id=str(listing_id),
                title=_first(row, "title", "name", "marketplace_listing_title"),
                description=_first(row, "description", "body", "marketplace_listing_description"),
                price_cents=_coerce_price_cents(_first(row, "price", "amount", "listing_price")),
                currency=str(_first(row, "currency", "price_currency") or "USD"),
                url=_first(row, "url", "listing_url", "permalink"),
                raw=row,
            )
        )
    return out
