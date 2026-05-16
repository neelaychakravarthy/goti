"""Shared defensive helpers for Bright Data row -> `Listing` parsers.

Round-3 introduces 3 additional marketplace parsers (Nextdoor / OfferUp /
Craigslist) that all need the same two helpers `fb_marketplace.py` uses
inline. Factored out here to avoid 3x duplication. `fb_marketplace.py` is
deliberately NOT refactored (drive-by ban — round-1 module).
"""

from __future__ import annotations

from typing import Any


def first(row: dict, *keys: str) -> Any:
    """Return the first non-empty value among `keys` in `row`, else None."""
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def coerce_price_cents(raw_price: Any) -> int | None:
    """Best-effort price -> integer cents.

    Bright Data rows return prices as numbers or as strings like "$249" or
    "249.00 USD". Strip non-numeric, parse as float, multiply by 100. Return
    None if it doesn't parse. Mirrors `fb_marketplace._coerce_price_cents`.
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
