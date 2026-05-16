"""Approval routes — DB-backed (Pass 2) + real Actionbook MCP (Pass 3).

On approve: records the buyer_agent message into ``message_threads``,
dispatches the outbound text via Actionbook (mocked when
``GOTI_USE_MOCKS=1``; real MCP-over-HTTP via
``api/integrations/actionbook/client.py`` otherwise), and marks the
approval_queue row resolved.

On reject: marks the row resolved with ``decision="reject"``. The job
stays open; re-drafting is out of scope for this Pass.

AgentField pause-resume: we **don't** call back to the af-server to
resolve the negotiator's ``app.pause()`` because the negotiator was
invoked with ``skip_pause=True`` (see ``api/orchestration/jobs.py``
docstring). The webhook discovery work done during Pass 2's
investigation found that the only way to externally resolve a pause is
to POST to the agent's own ``/webhooks/approval`` endpoint (the
agentfield client library does NOT expose a "submit approval"
helper) — this is brittle and unnecessary given the skip_pause
workaround.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import mocks
from api.config import get_settings
from api.contracts import ApprovalDecisionRequest, ApprovalDecisionResponse
from api.db import get_session
from api.integrations.actionbook import client as ab_client
from api.mocks import actionbook as mock_actionbook
from api.mocks import discovery as mock_discovery
from api.models import ApprovalQueueItem, Job as JobORM, MessageThread
from api.orchestration import jobs as orch_jobs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["approvals"])


def _resolve_marketplace_for_listing(listing_id: str) -> str:
    """Best-effort lookup of the listing's marketplace.

    Listings aren't persisted in Stream B's schema (Stream C owns
    ``listings_cache``), so we re-use the discovery mock to determine
    which marketplace a listing came from. Falls back to ``"fb"`` for
    unknown listings — the most common case in the demo path.

    TODO(stream-c): once ``listings_cache`` lands, read marketplace
    from the DB instead of round-tripping through the mock.
    """
    candidates = mock_discovery.search(query="", max_per_source=20)
    for li in candidates:
        if li.id == listing_id:
            return li.marketplace
    logger.info(
        "approvals: marketplace unknown for listing=%s; defaulting to 'fb'",
        listing_id,
    )
    return "fb"


async def _dispatch_outbound(
    *,
    user_id: str,
    listing_id: str,
    text: str,
    session: AsyncSession,
) -> str:
    """Send the approved message via the appropriate Actionbook seam.

    - ``GOTI_USE_MOCKS=1``: deterministic in-memory mock.
    - ``GOTI_USE_MOCKS=0``: real Actionbook MCP via the OAuth-linked
      session. If the user hasn't completed OAuth yet (no active row in
      ``integration_accounts``), or the MCP call raises, the exception
      bubbles to the caller which logs + treats as non-fatal so the
      approval flow still progresses (the user can see the message in
      the thread; the upstream send just didn't happen).

    Returns the message_id from the dispatch path.
    """
    if mocks.use_mocks():
        return mock_actionbook.send_message(
            user_id=user_id, listing_id=listing_id, text=text
        )
    marketplace = _resolve_marketplace_for_listing(listing_id)
    return await ab_client.send_message(
        user_id=user_id,
        listing_id=listing_id,
        text=text,
        marketplace=marketplace,
        db=session,
    )


@router.post(
    "/jobs/{job_id}/approvals/{card_id}",
    response_model=ApprovalDecisionResponse,
)
async def decide_approval(
    job_id: str,
    card_id: str,
    payload: ApprovalDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> ApprovalDecisionResponse:
    settings = get_settings()

    card = await ApprovalQueueItem.get(session, card_id)
    if card is None or card.job_id != job_id:
        raise HTTPException(
            status_code=404,
            detail=f"approval card not found: job={job_id} card={card_id}",
        )
    if card.decision is not None:
        raise HTTPException(
            status_code=409,
            detail=f"approval card already decided: {card.decision}",
        )

    job = await JobORM.get(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")

    if payload.decision == "approve":
        text_to_send = (
            payload.edited_text
            if isinstance(payload.edited_text, str) and payload.edited_text.strip()
            else card.draft_text
        )
        # Persist the outbound message first so the user sees it in the
        # thread immediately on next read — dispatch is best-effort.
        await MessageThread.append(
            session,
            job_id=job_id,
            role="buyer_agent",
            text=text_to_send,
        )
        try:
            message_id = await _dispatch_outbound(
                user_id=job.user_id,
                listing_id=job.listing_id,
                text=text_to_send,
                session=session,
            )
            logger.info(
                "decide_approval: dispatched job=%s card=%s msg_id=%s",
                job_id,
                card_id,
                message_id,
            )
        except Exception:  # noqa: BLE001 — dispatch failures shouldn't 500 the approval
            # TODO: record dispatch failures on the job (e.g. a
            # ``dispatch_error`` column on ``message_threads``) so the UI
            # can surface "send failed; retry?". Out of scope for Pass 3.
            logger.exception("decide_approval: outbound dispatch failed (non-fatal)")

        await ApprovalQueueItem.resolve(session, card_id, "approve")
        await orch_jobs.advance_job_state(
            session,
            job_id=job_id,
            new_status="awaiting_seller_reply",
            bump_last_message_at=True,
        )
    else:
        # reject: keep the row's draft, mark resolved with the rejection.
        await ApprovalQueueItem.resolve(session, card_id, "reject")
        await orch_jobs.advance_job_state(
            session, job_id=job_id, new_status="active"
        )

    await session.commit()
    # Suppress unused-import warnings for `settings` (we may need it for
    # multi-user flows in Pass 3).
    _ = settings
    return ApprovalDecisionResponse(
        ok=True,
        job_id=job_id,
        card_id=card_id,
        decision=payload.decision,
    )
