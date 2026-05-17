"""Approval routes — DB-backed + AgentField bridge.

Two complementary surfaces:

1. **``POST /api/approvals/{id}``** (the frontend-shape route).
   ``{id}`` is the AgentField ``approval_request_id`` (the stable id the
   reasoner included in ``app.pause()`` and that we surfaced via
   ``api/routes/agent_bridge.py``). On decision:
   - Records the buyer_agent message into ``message_threads`` (when the
     queue row is bound to a Job; pause-only flows skip this step).
   - Dispatches the outbound text via the browser-use agent over the
     user's Browserbase context (Claude reasons through the marketplace
     DOM and clicks Send) on approve.
   - Marks the linked ``Notification`` as ``resolved``.
   - Bridges the decision to AgentField by POSTing to the agent's stored
     ``callback_url`` (``/webhooks/approval``) so the paused reasoner
     future resolves.
   - Webhook-POST failures are logged + swallowed (the agent's pause
     will time out after ``expires_in_hours`` — never block the user on
     a flaky agent server).

   **``close_deal`` decision** — a third decision value besides
   ``approve`` / ``reject``. When the user picks ``close_deal`` on an
   approval bound to a Job, the route:
   - Marks the queue row decided (``decision="close_deal"``, feedback
     ``{final_price, agreed_text}``).
   - Transitions the Job to ``status="closed"`` + records ``final_price``.
   - Writes a Case to EverOS via
     ``memory_store.write_case_on_completion`` so the Memory Bank
     populates from this completed negotiation.
   - Emits a ``deal_closed`` notification.
   - POSTs back to the agent webhook with ``decision="closed"`` so the
     paused negotiator reasoner returns cleanly.

2. **``POST /api/jobs/{job_id}/approvals/{card_id}``** — legacy alias.
   Looks up the approval by ``(job_id, card_id)`` (the queue row's
   UUID PK) and dispatches the same lifecycle. Kept so older clients
   that haven't migrated to the AgentField id still work.

The pre-Pass-1 "skip_pause workaround" comment block in this file has
been removed — orchestration now uses the real ``app.pause()`` path
end-to-end via the bridge.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api import memory_store, notifications as notif_queue
from api.auth import current_user
from api.contracts import ApprovalDecisionRequest, ApprovalDecisionResponse
from api.db import get_session
from api.integrations.browser_agent import actions as agent_actions
from api.models import ApprovalQueueItem, Job as JobORM, MessageThread, Notification, User
from api.orchestration import jobs as orch_jobs
from api.rate_limit import limit as _rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["approvals"])


# ---------------------------------------------------------------------------
# Helpers — shared by the two routes
# ---------------------------------------------------------------------------


async def _resolve_listing_details(
    listing_id: str,
) -> tuple[str, str]:
    """Best-effort lookup of ``(marketplace, listing_url)`` for a listing.

    Reads from ``listings_cache`` — the canonical source after a hunt's
    discovery phase has run. The hunt lifecycle now populates this
    table for every discovered listing, so the cache miss path is rare
    in production. On miss we default the marketplace to ``"fb"`` (the
    historic default) + return an empty URL, which makes the
    browser-agent dispatch a no-op (it requires a URL).
    """
    try:
        from sqlalchemy import select

        from api.db import AsyncSessionLocal
        from api.models import ListingCache

        async with AsyncSessionLocal() as s:
            rows = await s.execute(
                select(ListingCache).where(ListingCache.listing_id == listing_id)
            )
            row = rows.scalars().first()
            if row is not None:
                marketplace = row.marketplace or "fb"
                return marketplace, (row.url or "")
    except Exception:  # noqa: BLE001 — DB best-effort
        logger.exception(
            "approvals._resolve_listing_details: listings_cache lookup failed for %s",
            listing_id,
        )

    logger.info(
        "approvals._resolve_listing_details: unknown listing=%s; default fb, no url",
        listing_id,
    )
    return "fb", ""


async def _dispatch_outbound(
    *,
    user_id: str,
    listing_id: str,
    text: str,
    hunt_id: str | None = None,
    job_id: str | None = None,
) -> str:
    """Send the approved message via the browser-use agent over Browserbase.

    Resolves the user's Browserbase Context id from
    ``integration_accounts`` (any active row — a single Context spans
    all marketplaces the user signed into) and dispatches via
    ``browser_agent.actions.send_message``. Returns an empty string
    (logging a warning) when no active link exists or when the
    listing's URL isn't in ``listings_cache``.
    """
    from api.db import AsyncSessionLocal
    from api.models import IntegrationAccountRow

    marketplace, listing_url = await _resolve_listing_details(listing_id)

    context_id: str | None = None
    async with AsyncSessionLocal() as s:
        # Any active row works — a single Browserbase Context covers
        # every marketplace the user signed into. Prefer the row for
        # the listing's marketplace if present, otherwise fall back to
        # the first active row for the user.
        provider = "nextdoor" if marketplace == "nextdoor" else "fb"
        row = await IntegrationAccountRow.get(s, user_id, provider)
        if row and row.browserbase_context_id:
            context_id = row.browserbase_context_id
        else:
            active_rows = await IntegrationAccountRow.list_active_for_user(
                s, user_id
            )
            for r in active_rows:
                if r.browserbase_context_id:
                    context_id = r.browserbase_context_id
                    break
    if not context_id:
        logger.warning(
            "_dispatch_outbound: no Browserbase context for user=%s (listing=%s); "
            "skipping dispatch",
            user_id,
            listing_id,
        )
        return ""
    if not listing_url:
        logger.warning(
            "_dispatch_outbound: no listing_url for listing=%s in listings_cache; "
            "skipping dispatch (browser-agent needs a URL to open)",
            listing_id,
        )
        return ""

    return await agent_actions.send_message(
        context_id=context_id,
        listing_url=listing_url,
        listing_id=listing_id,
        message_text=text,
        marketplace=marketplace,
        hunt_id=hunt_id,
        job_id=job_id,
    )


async def _post_agent_webhook(
    *,
    callback_url: str,
    execution_id: Optional[str],
    approval_request_id: str,
    decision: str,
    feedback: Any,
) -> None:
    """POST the resolution to the agent's ``/webhooks/approval`` endpoint.

    Body shape matches what ``agent_server.approval_webhook`` (in the
    agentfield SDK) expects — ``execution_id``, ``decision``,
    ``approval_request_id``, ``feedback``, optional ``response``.

    Decision mapping: our domain values ("approve" / "reject") map to
    AgentField's ("approved" / "rejected").

    Failures are LOGGED, not raised — never block the user's approval
    on a flaky agent server. The agent's ``app.pause()`` will time out
    after ``expires_in_hours`` if the webhook never arrives.
    """
    af_decision = {
        "approve": "approved",
        "reject": "rejected",
        # AgentField doesn't define a native ``"closed"`` decision; we
        # send ``"approved"`` so the reasoner future resolves cleanly,
        # and surface the close-deal context via the ``feedback`` /
        # ``response`` payload so the agent can branch downstream.
        "close_deal": "approved",
    }.get(decision, decision)
    body: dict[str, Any] = {
        "approval_request_id": approval_request_id,
        "decision": af_decision,
    }
    if execution_id:
        body["execution_id"] = execution_id
    if isinstance(feedback, (str, int, float, bool)) or feedback is None:
        body["feedback"] = "" if feedback is None else str(feedback)
    else:
        # Complex feedback (dict / list) — pass as JSON-encoded string so the
        # SDK's webhook handler can parse it back. It also accepts dicts on
        # the ``response`` field — include both for compatibility.
        import json as _json

        body["feedback"] = _json.dumps(feedback)
        body["response"] = feedback

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(callback_url, json=body)
            logger.info(
                "_post_agent_webhook: POST %s -> %s",
                callback_url,
                response.status_code,
            )
    except Exception:  # noqa: BLE001 — webhook is best-effort
        logger.exception(
            "_post_agent_webhook: POST to %s failed for approval_request_id=%s",
            callback_url,
            approval_request_id,
        )


def _parse_close_deal_feedback(
    edited_text: Optional[str], feedback: Any
) -> tuple[Optional[float], Optional[str]]:
    """Pull ``(final_price, agreed_text)`` out of a close_deal payload.

    Accepts either a feedback dict with explicit keys
    (``{final_price, agreed_text}``), a bare numeric ``final_price``,
    or a free-form string falling back to ``edited_text``.
    """
    final_price: Optional[float] = None
    agreed_text: Optional[str] = (
        edited_text if isinstance(edited_text, str) and edited_text.strip() else None
    )
    if isinstance(feedback, dict):
        candidate = feedback.get("final_price")
        if isinstance(candidate, (int, float)):
            final_price = float(candidate)
        elif isinstance(candidate, str):
            try:
                final_price = float(
                    candidate.replace("$", "").replace(",", "").strip()
                )
            except ValueError:
                final_price = None
        txt = feedback.get("agreed_text")
        if isinstance(txt, str) and txt.strip():
            agreed_text = txt
    elif isinstance(feedback, (int, float)):
        final_price = float(feedback)
    return final_price, agreed_text


async def _resolve_card_lifecycle(
    *,
    session: AsyncSession,
    card: ApprovalQueueItem,
    decision: str,
    edited_text: Optional[str],
    feedback: Any,
) -> Optional[JobORM]:
    """Shared post-decision side effects for both approval routes.

    1. If the row is bound to a Job, persist the message + dispatch via
       Actionbook on approve.
    2. Mark the queue row resolved.
    3. Mark the linked Notification resolved.
    4. Bridge the decision to AgentField via the agent webhook.
    5. Advance the job state when bound.

    On ``decision == "close_deal"`` the route handler additionally writes
    a Case + emits a ``deal_closed`` notification (handled by the caller
    after commit). The returned ``JobORM`` lets the caller perform
    those follow-ups against the latest snapshot.

    Caller commits.
    """
    # --- step 1 + 5: message + dispatch + job-state ---
    job: Optional[JobORM] = None
    if card.job_id:
        job = await JobORM.get(session, card.job_id)

    # ---- Discovery clarification short-circuit ----
    # Approvals minted by ``request_discovery_clarification`` aren't
    # tied to a Job and don't dispatch outbound messages. Detect them
    # via ``request_payload.clarify_type`` and route the answer to the
    # waiting asyncio.Event in the discovery loop, then resolve + bail
    # before the rest of the job-bound logic runs.
    request_payload = card.request_payload or {}
    if isinstance(request_payload, dict) and (
        request_payload.get("clarify_type") == "discovery_criteria"
    ):
        # The user's answer lives at ``feedback.answer`` (preferred) or
        # at ``feedback`` itself when sent as a plain string.
        answer: str | None = None
        if isinstance(feedback, dict):
            raw = feedback.get("answer") or feedback.get("value") or feedback.get("text")
            if isinstance(raw, str) and raw.strip():
                answer = raw.strip()
        elif isinstance(feedback, str) and feedback.strip():
            answer = feedback.strip()
        elif isinstance(edited_text, str) and edited_text.strip():
            answer = edited_text.strip()

        await ApprovalQueueItem.resolve(
            session,
            card.id,
            decision if decision in ("approve", "reject") else "approve",
            feedback={"answer": answer} if answer is not None else None,
        )
        if card.approval_request_id and answer:
            from api.orchestration.hunts import deliver_discovery_clarification

            delivered = deliver_discovery_clarification(
                card.approval_request_id, answer
            )
            if not delivered:
                logger.warning(
                    "approvals: discovery clarification answer arrived for "
                    "approval_request_id=%s but no waiting event found "
                    "(loop may have moved on)",
                    card.approval_request_id,
                )

        # Resolve the linked notification + return — none of the
        # job-bound branches apply to a discovery clarification.
        notif = await Notification.get_by_approval_request_id(
            session, card.approval_request_id or ""
        )
        if notif is not None and notif.status not in ("resolved", "dismissed"):
            await Notification.mark_resolved(session, notif.id)
        return job  # type: ignore[return-value]

    if decision == "approve":
        text_to_send = (
            edited_text
            if isinstance(edited_text, str) and edited_text.strip()
            else (card.draft_text or "")
        )
        if job is not None and text_to_send:
            await MessageThread.append(
                session,
                job_id=job.id,
                role="buyer_agent",
                text=text_to_send,
            )
            try:
                message_id = await _dispatch_outbound(
                    user_id=job.user_id,
                    listing_id=job.listing_id,
                    text=text_to_send,
                    hunt_id=job.hunt_id,
                    job_id=str(job.id),
                )
                logger.info(
                    "approvals: dispatched job=%s msg_id=%s", job.id, message_id
                )
            except Exception:  # noqa: BLE001 — dispatch failures shouldn't 500 approval
                logger.exception(
                    "approvals: outbound dispatch failed (non-fatal) for job=%s",
                    job.id,
                )
        await ApprovalQueueItem.resolve(
            session,
            card.id,
            "approve",
            feedback={"edited_text": edited_text, "feedback": feedback}
            if edited_text or feedback is not None
            else None,
        )
        if job is not None:
            await orch_jobs.advance_job_state(
                session,
                job_id=job.id,
                new_status="awaiting_seller_reply",
                bump_last_message_at=True,
            )
            # Phase E: kick off the end-of-negotiation classifier in the
            # background after a buyer message lands. The reasoner reads
            # the full conversation + listing + target_price and writes
            # ``ready_to_close`` back to the Job row. Fire-and-forget so
            # the user's approval click doesn't block on the LLM.
            orch_jobs.spawn_classifier_in_background(job.id)
    elif decision == "close_deal":
        final_price, agreed_text = _parse_close_deal_feedback(
            edited_text, feedback
        )
        await ApprovalQueueItem.resolve(
            session,
            card.id,
            "close_deal",
            feedback={
                "final_price": final_price,
                "agreed_text": agreed_text,
            },
        )
        if job is not None:
            job = await JobORM.close_at_price(
                session, job_id=job.id, final_price=final_price
            )
            # Close the parent hunt as well — the user got their deal,
            # so the streaming discovery loop should stop and any other
            # in-flight negotiations under this hunt are now moot. The
            # discovery loop polls ``Hunt.status`` each iteration and
            # exits cleanly when it sees ``closed``.
            if job.hunt_id:
                from api.models import Hunt as HuntORM

                await HuntORM.update_status(session, job.hunt_id, "closed")
                await HuntORM.update_lifecycle_phase(
                    session, job.hunt_id, "closed"
                )
    else:
        await ApprovalQueueItem.resolve(
            session,
            card.id,
            "reject",
            feedback={"feedback": feedback} if feedback is not None else None,
        )
        if job is not None:
            await orch_jobs.advance_job_state(
                session,
                job_id=job.id,
                new_status="active",
            )

    # --- step 3: resolve linked notification ---
    if card.approval_request_id:
        notif = await Notification.get_by_approval_request_id(
            session, card.approval_request_id
        )
        if notif is not None and notif.status not in ("resolved", "dismissed"):
            await Notification.mark_resolved(session, notif.id)

    # --- step 4: agent webhook bridge (after commit, fire-and-forget on errors) ---
    # We POST AFTER commit so the DB transition is durable before we
    # signal the agent. Failure is non-fatal (agent times out gracefully).
    return job


async def _write_case_and_emit_deal_closed(
    *,
    job: JobORM,
    final_price: Optional[float],
    agreed_text: Optional[str],
) -> None:
    """Write the Case to EverOS + emit a ``deal_closed`` notification.

    Called from the route handler after commit (durable transition first).
    All failures are logged + swallowed — close-deal must succeed even if
    EverOS / the notification pipe are flaky.
    """
    from api.db import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as s:
            job_row = await JobORM.get(s, job.id)
            if job_row is not None:
                await memory_store.write_case_on_completion(job_row, s)
    except Exception:  # noqa: BLE001 — Case write is best-effort
        logger.exception(
            "_write_case_and_emit_deal_closed: write_case_on_completion failed "
            "job=%s (non-fatal)",
            job.id,
        )

    try:
        async with AsyncSessionLocal() as s:
            body = (
                f"Agreed at ${int(final_price)}"
                if isinstance(final_price, (int, float))
                else "Negotiation concluded."
            )
            notif = await Notification.create(
                s,
                user_id=job.user_id,
                kind="deal_closed",
                title="Deal closed",
                body=body,
                target_href=f"/deal/{job.id}",
                job_id=job.id,
                payload={
                    "job_id": job.id,
                    "final_price": final_price,
                    "agreed_text": agreed_text,
                },
            )
            await s.commit()
            await notif_queue.enqueue(notif.to_event_dict())
    except Exception:  # noqa: BLE001
        logger.exception(
            "_write_case_and_emit_deal_closed: deal_closed notif failed job=%s",
            job.id,
        )


@router.post("/approvals/{id}")
@_rate_limit("30/minute")
async def decide_approval_by_request_id(
    request: Request,
    id: str,  # noqa: A002 — matches frontend path param naming
    body: dict[str, Any] = Body(default_factory=dict),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Frontend-shape approval-decision route, keyed on AgentField's id.

    Body: ``{decision: "approve"|"reject"|"close_deal", feedback?: any, edited_text?: string}``.

    For ``decision="close_deal"`` the ``feedback`` carries
    ``{final_price: number, agreed_text: str}``; the route transitions
    the Job to ``closed`` + writes a Case + emits a ``deal_closed``
    notification.

    Returns ``{ok: true, approval_id, decision, edited?, agent_notified}``.
    """
    decision_raw = str(body.get("decision") or "").lower()
    if decision_raw in ("approve", "approved"):
        decision = "approve"
    elif decision_raw in ("reject", "rejected"):
        decision = "reject"
    elif decision_raw in ("close_deal", "close-deal", "closed"):
        decision = "close_deal"
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "decision must be 'approve', 'reject', or 'close_deal', "
                f"got {decision_raw!r}"
            ),
        )

    edited_text = body.get("edited_text")
    if edited_text is not None and not isinstance(edited_text, str):
        edited_text = str(edited_text)
    feedback = body.get("feedback")

    card = await ApprovalQueueItem.get_by_approval_request_id(session, id)
    if card is None:
        # The frontend may pass synthetic ids (e.g. "ap-<suffix>") from
        # fixture-driven flows; return ok=true idempotently so the UI
        # progresses, but flag the missing row so logs are honest.
        logger.warning(
            "decide_approval_by_request_id: unknown approval_request_id=%s — "
            "treating as no-op (likely a synthetic fixture id)",
            id,
        )
        return {
            "ok": True,
            "approval_id": id,
            "decision": decision,
            "edited": bool(edited_text),
            "agent_notified": False,
            "matched_row": False,
        }

    if card.decision is not None:
        raise HTTPException(
            status_code=409,
            detail=f"approval already decided: {card.decision}",
        )

    # Ownership check when the row is bound to a job — the job's user
    # must match. Unbound rows (no job_id) fall through; the bridge
    # itself ties them to the current user via the AgentField payload.
    if card.job_id:
        job_row = await JobORM.get(session, card.job_id)
        if job_row is not None and job_row.user_id != str(user.id):
            raise HTTPException(
                status_code=403,
                detail="approval does not belong to the current user",
            )

    # Snapshot bridge fields BEFORE the lifecycle mutates the row.
    callback_url = card.agent_callback_url
    execution_id = card.execution_id

    closed_job = await _resolve_card_lifecycle(
        session=session,
        card=card,
        decision=decision,
        edited_text=edited_text,
        feedback=feedback,
    )
    await session.commit()

    # Close-deal post-commit follow-ups: write Case to EverOS + emit
    # ``deal_closed`` notification. Run after commit so the durable
    # transition wins even if EverOS / the notification pipe are flaky.
    if decision == "close_deal" and closed_job is not None:
        final_price, agreed_text = _parse_close_deal_feedback(
            edited_text, feedback
        )
        await _write_case_and_emit_deal_closed(
            job=closed_job,
            final_price=final_price,
            agreed_text=agreed_text,
        )

    # Bridge to AgentField AFTER commit (durable).
    agent_notified = False
    if callback_url:
        await _post_agent_webhook(
            callback_url=callback_url,
            execution_id=execution_id,
            approval_request_id=id,
            decision=decision,
            # On approve, propagate edited_text as feedback (matches
            # AgentField's ApprovalResult.feedback convention — see
            # client.py:74). On reject, propagate the user-provided
            # feedback dict / string. On close_deal, send the full
            # ``{final_price, agreed_text}`` payload so the reasoner
            # can return cleanly.
            feedback=(edited_text or feedback),
        )
        agent_notified = True

    return {
        "ok": True,
        "approval_id": id,
        "decision": decision,
        "edited": bool(edited_text),
        "agent_notified": agent_notified,
        "matched_row": True,
    }


@router.post(
    "/jobs/{job_id}/approvals/{card_id}",
    response_model=ApprovalDecisionResponse,
)
async def decide_approval_legacy(
    job_id: str,
    card_id: str,
    payload: ApprovalDecisionRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ApprovalDecisionResponse:
    """Legacy approval route — keyed on the queue row's UUID PK + job_id.

    Same lifecycle as ``POST /api/approvals/{id}`` but accepts the
    internal id pair. Kept for backwards compatibility with pre-bridge
    clients.
    """
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
    if job.user_id != str(user.id):
        raise HTTPException(
            status_code=403,
            detail="approval does not belong to the current user",
        )

    callback_url = card.agent_callback_url
    execution_id = card.execution_id
    approval_request_id = card.approval_request_id

    closed_job = await _resolve_card_lifecycle(
        session=session,
        card=card,
        decision=payload.decision,
        edited_text=payload.edited_text,
        feedback=None,
    )
    await session.commit()

    # Close-deal post-commit follow-ups (mirrors the new route's behavior).
    if payload.decision == "close_deal" and closed_job is not None:
        final_price, agreed_text = _parse_close_deal_feedback(
            payload.edited_text, None
        )
        await _write_case_and_emit_deal_closed(
            job=closed_job,
            final_price=final_price,
            agreed_text=agreed_text,
        )

    if callback_url and approval_request_id:
        await _post_agent_webhook(
            callback_url=callback_url,
            execution_id=execution_id,
            approval_request_id=approval_request_id,
            decision=payload.decision,
            feedback=payload.edited_text,
        )

    return ApprovalDecisionResponse(
        ok=True,
        job_id=job_id,
        card_id=card_id,
        decision=payload.decision,
    )
