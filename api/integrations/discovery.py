"""B->C discovery entry point.

`search()` dispatches to the real Bright Data client or to the mock fixture
based on `settings.use_mocks`. Dispatch happens at call time (not import time)
so tests can flip the flag between cases without re-importing this module.
"""

from api.contracts import Listing
from api.settings import settings


async def search(
    query: str,
    marketplaces: list[str],
    max_per_source: int = 10,
) -> list[Listing]:
    """Search the given marketplaces for `query`.

    Stream B calls this from the discovery agent. The async signature is the
    Stream C round-1 convention; future Actionbook signatures should follow.
    """
    if settings.use_mocks:
        from api.mocks.discovery import search as _mock_search

        return await _mock_search(query, marketplaces, max_per_source)

    from api.integrations.bright_data.client import fetch_listings

    out: list[Listing] = []
    for mp in marketplaces:
        try:
            out.extend(await fetch_listings(mp, query, max_per_source))
        except NotImplementedError:
            # Only `fb` is wired this round; skip other marketplaces so a
            # caller asking for ["fb", "nextdoor"] still gets fb results.
            continue
    return out
