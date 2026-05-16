"""Jobs routes — DB-backed (Pass 2).

Replaces the Pass-1 fixture stubs with real Postgres + reasoner-driven
handlers. See ``api/orchestration/jobs.py`` for the lifecycle docstring.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api import mocks
from api.config import get_settings
from api.contracts import Job, NegotiateResponse
from api.db import get_session
from api.mocks import discovery as mock_discovery
from api.models import ApprovalQueueItem, Job as JobORM
from api.orchestration import jobs as orch_jobs
from api.orchestration.sse import job_event_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])


# ---------------------------------------------------------------------------
# POST /api/listings/{listing_id}/negotiate


def _resolve_listing(listing_id: str):
    """Look up a Listing by id; falls back to mocks/fixtures.

    Listings aren't persisted in Stream B's schema (Stream C's
    listings_cache table eventually holds them). For Pass 2 we resolve
    from the mocks fixtures so the negotiate path is exercisable
    end-to-end without Bright Data.
    """
    candidates = mock_discovery.search(query="", max_per_source=20)
    for li in candidates:
        if li.id == listing_id:
            return li
    return None


@router.post("/listings/{listing_id}/negotiate", response_model=NegotiateResponse)
async def negotiate(
    listing_id: str,
    session: AsyncSession = Depends(get_session),
) -> NegotiateResponse:
    settings = get_settings()
    listing = _resolve_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"unknown listing_id: {listing_id}")

    # Best-effort valuation -> target_price (None on failure).
    target_price: Optional[float] = await orch_jobs.invoke_valuation_for_listing(
        listing, budget=None, user_id=settings.demo_user_id
    )

    job = await orch_jobs.spawn_job(
        session,
        listing=listing,
        target_price=target_price,
        user_id=settings.demo_user_id,
    )
    await session.commit()

    # Seed BATNA via the coordinator reasoner (best-effort, non-blocking on
    # error since BATNA leverage is enrichment, not load-bearing for round 1).
    await orch_jobs.seed_batna_via_coordinator(
        goal_id=listing_id,  # surrogate; goals aren't persisted
        listings=[listing],
        target_listing_ids=[listing_id],
        target_price=float(target_price) if target_price is not None else 0.0,
        user_id=settings.demo_user_id,
    )

    # Invoke the negotiator with skip_pause=True so it returns the draft
    # directly. We then create an approval_queue row from the response.
    negotiation = await orch_jobs.invoke_negotiator_for_draft(
        job_id=job.id,
        conversation=[],
        target_price=target_price,
        user_id=settings.demo_user_id,
    )
    await ApprovalQueueItem.create(
        session,
        job_id=job.id,
        draft_text=negotiation["draft_text"],
        draft_reasoning=negotiation.get("draft_reasoning"),
    )
    await session.commit()

    logger.info(
        "negotiate: job=%s listing=%s target_price=%s", job.id, listing_id, target_price
    )
    return NegotiateResponse(job_id=job.id)


# ---------------------------------------------------------------------------
# GET /api/jobs


@router.get("/jobs", response_model=list[Job])
async def list_jobs(
    session: AsyncSession = Depends(get_session),
) -> list[Job]:
    settings = get_settings()
    rows = await JobORM.list_for_user(session, settings.demo_user_id)
    results: list[Job] = []
    for r in rows:
        composed = await orch_jobs.build_job_response(session, r.id)
        if composed is not None:
            results.append(composed)
    return results


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}


@router.get("/jobs/{job_id}", response_model=Job)
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> Job:
    composed = await orch_jobs.build_job_response(session, job_id)
    if composed is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
    return composed


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/stream — SSE


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str) -> StreamingResponse:
    # NOTE: the generator opens its own DB session per-iteration; we do NOT
    # pass the dependency-injected session because that would close when
    # this route returns (before the generator yields its first event).
    return StreamingResponse(
        job_event_stream(job_id),
        media_type="text/event-stream",
    )


# Reference to the imported `mocks` symbol so static analyzers don't strip
# it (used indirectly through ``_resolve_listing`` -> ``mock_discovery``).
_ = mocks
