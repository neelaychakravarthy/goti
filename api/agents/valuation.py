"""AgentField reasoner: score a listing's fair price + target negotiation price.

Shares `app` (and therefore `app.memory`) with the other three reasoners
(clarifier, negotiator, coordinator) — see `_af_app.py` for the rationale.

`app.memory.get` confirmed async against agentfield 0.1.84 in Pass-1
verification. If the docker-compose build pins a diverging version,
adjust the await accordingly.
"""

from __future__ import annotations

import logging

from api.agents._af_app import app
from api.llm import draft_valuation

logger = logging.getLogger(__name__)


@app.reasoner()
async def assess_listing(
    listing: dict,
    user_budget: float | None = None,
    user_id: str = "demo_user",
) -> dict:
    """Score a listing's fair price + walk-away + target negotiation price.

    Reads user_budget from shared memory if not passed (key:
    ``user_budget:{user_id}``). Falls back to the listing's asking price as
    a last-resort budget if neither is available — so the reasoner never
    raises a missing-state error during agent dispatch.

    Returns: ``{fair_price_estimate, walk_away_price, target_price, reasoning}``.
    On LLM parse error, `draft_valuation` returns a safe fallback rather
    than raising — see `api/llm.py`.
    """
    budget = user_budget
    if budget is None:
        try:
            stored = await app.memory.get(f"user_budget:{user_id}")
        except Exception:  # noqa: BLE001 — memory backend may be unavailable
            logger.exception("valuation: app.memory.get failed; falling back to listing price.")
            stored = None
        if isinstance(stored, (int, float)):
            budget = float(stored)
        else:
            # Final fallback: use the listing's asking price as the budget so
            # the LLM has *something* to anchor on.
            try:
                budget = float(listing.get("price", 0.0))
            except (TypeError, ValueError):
                budget = 0.0
            logger.info(
                "valuation: no user_budget in memory; falling back to listing.price=%s", budget
            )

    logger.info(
        "valuation: assessing listing=%s budget=%s", listing.get("id", "<no-id>"), budget
    )
    return await draft_valuation(listing, budget)
