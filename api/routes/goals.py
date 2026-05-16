"""Goals routes.

Three endpoints:

- ``POST /api/goals`` — invokes the clarifier reasoner (via the
  ``goti`` Agent's ``ask_clarifying_question`` method) and returns a
  budget-related clarifying question. Also fires an EverOS Case stub
  write in the background.
- ``POST /api/goals/{goal_id}/clarify`` — accepts the user's budget,
  stashes it in the in-memory goal cache, and returns discovery listings
  (mocked when ``GOTI_USE_MOCKS=1``).
- ``GET /api/goals/{goal_id}/listings`` — re-fetches listings (same path
  as above).

Pass 2 sync: the reasoner URL now points at ``goti.ask_clarifying_question``
(node_id was renamed in Pass 1). The inline httpx forwarder was replaced
with ``orchestration.agents_client.invoke_reasoner``.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api import mocks
from api.contracts import (
    ClarifyRequest,
    ClarifyResponse,
    CreateGoalRequest,
    CreateGoalResponse,
    Listing,
    ListingsResponse,
)
from api.memory_store import write_case
from api.mocks import discovery as mock_discovery
from api.orchestration import jobs as orch_jobs
from api.orchestration.agents_client import invoke_reasoner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["goals"])


# ---------------------------------------------------------------------------
# Fixture listings — used as a fallback when ``use_mocks()`` is False but
# real Bright Data isn't wired yet (Stream C territory).


def _fixture_listings() -> list[Listing]:
    return [
        Listing(
            id="lst-1",
            title="Adjustable standing desk, walnut top",
            price=215.0,
            marketplace="fb",
            url="https://facebook.com/marketplace/item/1",
            image_url="https://placehold.co/600x400?text=Standing+Desk",
            seller_name="Maya R.",
            location="Mission District, SF",
            description="Electric height-adjust, used 6 months. Pickup only.",
        ),
        Listing(
            id="lst-2",
            title="Uplift V2 standing desk (gently used)",
            price=240.0,
            marketplace="nextdoor",
            url="https://nextdoor.com/for_sale/2",
            image_url="https://placehold.co/600x400?text=Uplift+Desk",
            seller_name="Diego M.",
            location="SoMa, SF",
            description="Bought new in 2024. Moving sale.",
        ),
        Listing(
            id="lst-3",
            title="FlexiSpot E7 standing desk frame + bamboo top",
            price=199.0,
            marketplace="offerup",
            url="https://offerup.com/item/3",
            image_url="https://placehold.co/600x400?text=FlexiSpot",
            seller_name="Priya S.",
            location="Inner Sunset, SF",
            description="Frame in great shape; small scratch on top.",
        ),
    ]


def _discover_listings(query: str) -> list[Listing]:
    """Resolve listings via mocks when enabled, fixtures otherwise."""
    if mocks.use_mocks():
        return mock_discovery.search(query=query, max_per_source=5)
    # Stream C will plug the real Bright Data path here.
    return _fixture_listings()


# ---------------------------------------------------------------------------
# POST /api/goals — clarifier reasoner via agents_client


async def _invoke_clarifier(goal: str) -> str:
    """Forward to the ``goti`` Agent's clarifier reasoner.

    Pass 2 sync: target is now ``goti.ask_clarifying_question`` (before
    Pass 1 the agent's node_id had a hyphenated suffix; that's gone now).
    """
    body = await invoke_reasoner("ask_clarifying_question", {"goal": goal})
    question = body.get("clarifying_question")
    if not isinstance(question, str) or not question.strip():
        raise HTTPException(
            status_code=502,
            detail=f"Reasoner returned no clarifying_question (raw={body!r})",
        )
    return question


@router.post("/goals", response_model=CreateGoalResponse)
async def create_goal(
    payload: CreateGoalRequest,
    background_tasks: BackgroundTasks,
) -> CreateGoalResponse:
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="goal text must be non-empty")

    goal_id = str(uuid.uuid4())
    clarifying_question = await _invoke_clarifier(payload.text)

    # Stash the goal text against goal_id so the /clarify endpoint can
    # re-use it when seeding discovery (goals aren't a persisted entity).
    orch_jobs.remember_goal(goal_id, payload.text)

    # Fire-and-forget: persist a Case stub to EverOS. Failures are swallowed
    # inside write_case so they never break the response.
    background_tasks.add_task(write_case, payload.text, clarifying_question)

    return CreateGoalResponse(
        goal_id=goal_id,
        clarifying_question=clarifying_question,
    )


# ---------------------------------------------------------------------------
# POST /api/goals/{goal_id}/clarify — kicks off discovery


@router.post("/goals/{goal_id}/clarify", response_model=ClarifyResponse)
async def submit_clarification(
    goal_id: str,
    payload: ClarifyRequest,
) -> ClarifyResponse:
    # Stash the budget alongside the goal text so /negotiate can read it.
    if payload.budget is not None:
        orch_jobs.remember_budget(goal_id, payload.budget)
    cached = orch_jobs.get_goal(goal_id)
    query = cached.get("text") or ""
    listings = _discover_listings(query)
    logger.info(
        "submit_clarification: goal=%s budget=%s -> %d listings",
        goal_id,
        payload.budget,
        len(listings),
    )
    return ClarifyResponse(listings=listings)


# ---------------------------------------------------------------------------
# GET /api/goals/{goal_id}/listings — re-fetch listings


@router.get("/goals/{goal_id}/listings", response_model=ListingsResponse)
async def list_listings(goal_id: str) -> ListingsResponse:
    cached = orch_jobs.get_goal(goal_id)
    query = cached.get("text") or ""
    return ListingsResponse(listings=_discover_listings(query))
