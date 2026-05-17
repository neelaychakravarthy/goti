"""End-to-end demo of the Goti negotiation flow.

Walks the discovery + Actionbook drivers in the same order the agent
loop exercises them, so you can SEE the data shape end-to-end. Requires
real Browserbase credentials in env;
``api/integrations/discovery.py`` raises if Browserbase isn't configured.

Run (from the repo root):
    ./api/.venv/bin/python scripts/demo_negotiation.py

Note: this is a dev-only CLI helper. Emoji section dividers are
intentional (visual scannability when run live).
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Make `api.*` imports work whether the script is run from the repo root or
# from inside scripts/. Python only puts the script's directory on sys.path
# by default, not the cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from api.contracts import Listing  # noqa: E402
from api.integrations.actionbook import fb, nextdoor  # noqa: E402
from api.integrations.discovery import search  # noqa: E402

QUERY = "standing desk under $250"
MARKETPLACES = ["fb", "nextdoor", "offerup", "craigslist"]
MAX_PER_SOURCE = 3
DISPLAY_PER_MARKETPLACE = 2
PROFILE_ID = "demo-buyer-001"


def _fmt_price(price: float | None) -> str:
    if price is None:
        return "n/a"
    if price == 0:
        return "FREE"
    return f"${price:.2f}"


def _group_by_marketplace(listings: list[Listing]) -> dict[str, list[Listing]]:
    out: dict[str, list[Listing]] = {}
    for l in listings:
        out.setdefault(l.marketplace, []).append(l)
    return out


def _divider(char: str = "-", width: int = 60) -> None:
    print(char * width)


async def main() -> None:
    # ---- Step 1: discovery ----------------------------------------------
    print()
    _divider("=")
    print(f"🔍  DISCOVERY  —  query={QUERY!r}  marketplaces={MARKETPLACES}")
    _divider("=")
    listings = await search(QUERY, MARKETPLACES, max_per_source=MAX_PER_SOURCE)
    grouped = _group_by_marketplace(listings)

    for mp in MARKETPLACES:
        mp_listings = grouped.get(mp, [])
        print(f"\n[{mp}]  {len(mp_listings)} listing(s)")
        if not mp_listings:
            print("    (no results)")
            continue
        for l in mp_listings[:DISPLAY_PER_MARKETPLACE]:
            print(f"    - {l.id}  {_fmt_price(l.price)}  {l.title}")

    # ---- Step 2: pick first fb + first nextdoor -------------------------
    print()
    _divider("=")
    print("🎯  PICK  —  one fb + one nextdoor (Actionbook only covers fb/nextdoor)")
    _divider("=")
    fb_listings = grouped.get("fb", [])
    nd_listings = grouped.get("nextdoor", [])
    if not fb_listings or not nd_listings:
        print("ERROR: expected at least one fb and one nextdoor listing from the mock.")
        sys.exit(1)
    fb_pick = fb_listings[0]
    nd_pick = nd_listings[0]
    print(f"\n  fb       -> {fb_pick.id}  {_fmt_price(fb_pick.price)}  {fb_pick.title}")
    print(f"  nextdoor -> {nd_pick.id}  {_fmt_price(nd_pick.price)}  {nd_pick.title}")
    print("  (skipping offerup + craigslist — no Actionbook driver this round)")

    # ---- Step 3: send opening offers ------------------------------------
    print()
    _divider("=")
    print("📤  SEND OPENING OFFERS")
    _divider("=")
    fb_opening = (
        f"Hi! Saw your listing \"{fb_pick.title}\". Would you take $200 cash, "
        "pickup today?"
    )
    nd_opening = (
        f"Hey neighbor — interested in \"{nd_pick.title}\". Any flexibility on "
        "price for a quick local pickup this weekend?"
    )

    fb_msg_id = await fb.send_message(PROFILE_ID, fb_pick.id, fb_opening)
    nd_msg_id = await nextdoor.send_message(PROFILE_ID, nd_pick.id, nd_opening)

    print(f"\n  fb       -> sent MessageId={fb_msg_id!r}")
    print(f"           opening: {fb_opening}")
    print(f"\n  nextdoor -> sent MessageId={nd_msg_id!r}")
    print(f"           opening: {nd_opening}")

    # ---- Step 4: fetch replies ------------------------------------------
    print()
    _divider("=")
    print("📥  FETCH REPLIES")
    _divider("=")
    since_ts = time.time() - 24 * 3600  # last 24h
    fb_replies = await fb.fetch_replies(PROFILE_ID, fb_pick.id, since_ts)
    nd_replies = await nextdoor.fetch_replies(PROFILE_ID, nd_pick.id, since_ts)

    print(f"\n  fb       -> {len(fb_replies)} reply(ies)")
    for r in fb_replies:
        print(f"    [{r.sender}] {r.text}")
    print(f"\n  nextdoor -> {len(nd_replies)} reply(ies)")
    for r in nd_replies:
        print(f"    [{r.sender}] {r.text}")

    # ---- Step 5: fake BATNA hint ----------------------------------------
    print()
    _divider("=")
    print("🧠  BATNA HINT  (sketch — what the agent would do next)")
    _divider("=")
    print(
        "  -> would tell FB seller about Nextdoor's $240 quick-pickup offer "
        "to anchor down on price"
    )
    print(
        "  -> would tell Nextdoor seller about FB's evening-pickup option to "
        "push for a faster commit"
    )
    print()


if __name__ == "__main__":
    asyncio.run(main())
