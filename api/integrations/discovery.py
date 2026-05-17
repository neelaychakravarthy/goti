"""Marketplace discovery via the browser-agent.

Routes every discovery call through ``browser_agent.actions.search_listings``,
which drives a browser-use AI agent over the user's Browserbase context.
Search now happens on the
user's actual logged-in marketplace sessions, so the listings the agent
returns are the same the user would see in their own browser.

Signature note: this module now takes a ``user_id`` + ``session`` because
the agent needs to resolve the user's Browserbase context_id from
``integration_accounts``. Callers must thread these through.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.contracts import Listing
from api.integrations.browser_agent import actions as agent_actions
from api.models import IntegrationAccountRow


async def search(
    user_id: str,
    query: str,
    marketplaces: list[str],
    max_per_source: int = 5,
    *,
    session: AsyncSession,
    hunt_id: str | None = None,
) -> list[Listing]:
    """Search via the user's logged-in marketplace sessions.

    Looks up any active ``integration_accounts`` row for the user (FB,
    Nextdoor — both share the same Browserbase Context) and dispatches
    a single browser-agent search task across the requested marketplaces.

    When ``hunt_id`` is provided, each Agent reasoning step is written
    to the hunt's activity timeline so the UI can render live progress.

    Raises ``RuntimeError`` when the user has no active marketplace
    links — discovery is impossible without a logged-in browser context,
    and the caller (hunt lifecycle) is expected to surface that via an
    error notification rather than silently returning an empty list.
    """
    rows = await IntegrationAccountRow.list_active_for_user(session, user_id)
    if not rows:
        raise RuntimeError(
            "No active marketplace links for this user — link any of "
            "FB Marketplace, Nextdoor, OfferUp, Craigslist via "
            "/api/integrations/{provider}/link + /finish first."
        )
    # Any provider's row works — a single Browserbase Context spans all
    # marketplaces the user signed into inside the Live View tab.
    context_id = rows[0].browserbase_context_id
    if not context_id:
        raise RuntimeError(
            "Integration account row is missing browserbase_context_id"
        )
    return await agent_actions.search_listings(
        context_id, query, marketplaces, max_per_source, hunt_id=hunt_id
    )
