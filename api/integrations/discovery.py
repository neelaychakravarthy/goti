"""B->C discovery entry point.

`search()` dispatches to the real Bright Data client or to the mock fixture
based on `settings.use_mocks`. Settings are resolved at call time so tests
can flip the flag between cases without re-importing this module.
"""

from api.config import get_settings
from api.contracts import Listing


async def search(
    query: str,
    marketplaces: list[str],
    max_per_source: int = 10,
) -> list[Listing]:
    """Search the given marketplaces for `query`.

    Stream B calls this from the discovery agent. The async signature is the
    Stream C round-1 convention; future Actionbook signatures should follow.
    """
    settings = get_settings()
    if settings.use_mocks:
        from api.mocks.discovery import search as _mock_search

        return await _mock_search(query, marketplaces, max_per_source)

    from api.integrations.bright_data.client import fetch_listings

    out: list[Listing] = []
    for mp in marketplaces:
        try:
            out.extend(await fetch_listings(mp, query, max_per_source))
        except NotImplementedError:
            # Skip marketplaces the Bright Data client doesn't know about
            # rather than failing the whole call.
            continue
    return out
