"""AgentField control-plane bridge.

FastAPI IS the AgentField control plane for Goti. Reasoners running on
the agent server (port 8080) call `app.pause()` / `client.register_agent()`
/ heartbeats / etc. against this router (mounted at ``/api/v1``).

Endpoints implemented (mapped from a careful read of
``agentfield/{agent,client,memory_events,agent_server}.py``):

| Endpoint                                                           | Source in agentfield                          | Purpose                                                                 |
|--------------------------------------------------------------------|-----------------------------------------------|-------------------------------------------------------------------------|
| POST ``/api/v1/agents/{node}/executions/{id}/request-approval``    | ``client.request_approval`` (client.py:1761)  | Turn ``app.pause()`` into a user-facing approval + notification.        |
| POST ``/api/v1/agents/{node}/executions/{id}/awaiter-status``      | ``client.notify_awaiter_status`` (1825)       | No-op accepting; ancestors-waiting propagation isn't load-bearing here. |
| GET  ``/api/v1/agents/{node}/executions/{id}/approval-status``     | ``client.get_approval_status`` (1862)         | Read the current decision from the approval_queue row.                  |
| POST ``/api/v1/nodes/register``                                    | ``client.register_agent`` (697)               | No-op accepting; we don't track agent registry server-side yet.         |
| POST ``/api/v1/nodes/{node_id}/heartbeat``                         | ``agent_field_handler.send_heartbeat`` (237)  | No-op accepting; eliminates heartbeat log noise.                        |
| POST ``/api/v1/nodes/{node_id}/shutdown``                          | ``client.shutdown_node``                       | No-op accepting.                                                        |
| PUT  ``/api/v1/nodes/{node_id}/health``                            | ``client.update_health`` (602)                | No-op accepting.                                                        |
| POST ``/api/v1/executions/{id}/status``                            | ``agent._post_execution_status`` (2502)       | No-op accepting; we don't observe per-execution lifecycle yet.          |
| WS   ``/api/v1/memory/events/ws``                                  | ``memory_events.connect`` (152)               | Accept silently — drops the 403 reconnect spam. We don't broadcast events. |

The ``request-approval`` handler is the load-bearing one. It:
1. Upserts an ``ApprovalQueueItem`` keyed by ``approval_request_id``.
2. Derives a notification (kind/title/body/target_href) from the payload.
3. Persists the notification + pushes it onto the in-memory queue so SSE
   subscribers get an instant push.
4. Returns the response shape AgentField expects (the SDK reads
   ``approval_request_id`` and ``approval_request_url`` off the JSON body).

When the user resolves the approval via ``POST /api/approvals/{id}``,
``api/routes/approvals.py`` POSTs to the agent's ``callback_url`` (stored
on the queue item) with the AgentField webhook body, which resumes the
paused reasoner.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi import WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api import notifications as notif_queue
from api.config import get_settings
from api.db import get_session
from api.models import ApprovalQueueItem, Notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agent-bridge"])


# Loopback addresses that are allowed to hit the AgentField bridge
# without a Google OAuth token. The bridge is called by the agent server
# co-located in the same container; opening it to the public internet
# would let anyone forge approvals. ``::1`` is IPv6 loopback; ``testclient``
# is FastAPI's TestClient when running unit tests.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _ensure_loopback_origin(request: Request) -> None:
    """Raise 403 if the request didn't come from a loopback peer.

    The AgentField agent server runs in the same container (port 8080)
    and calls our bridge at localhost:8000. We trust those calls without
    a Google OAuth token. Public-internet callers must use the
    Google-OAuth-protected routes instead.
    """
    client = request.client
    host = (client.host if client is not None else "") or ""
    if host not in _LOOPBACK_HOSTS:
        raise HTTPException(
            status_code=403,
            detail=(
                "AgentField bridge endpoints are loopback-only "
                f"(rejected host={host!r}). Use the public Goti API for "
                "user-facing operations."
            ),
        )


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


class RequestApprovalBody(BaseModel):
    """Body POSTed by ``agentfield.client.request_approval``.

    The SDK conditionally includes ``approval_request_url`` and
    ``callback_url`` only when non-empty (see client.py:1757-1760), so
    both are optional here. ``approval_request_id`` + ``expires_in_hours``
    are always sent. ``payload`` is a Goti-specific extension that the
    reasoner can stash inline for our notification builder; the upstream
    SDK does NOT send this field, so it stays optional.
    """

    approval_request_id: str
    approval_request_url: str = ""
    callback_url: str = ""
    expires_in_hours: int = 72
    # Goti extension: arbitrary structured data the reasoner wants to
    # surface on the notification (kind, question, draft_text, ...).
    payload: dict[str, Any] = Field(default_factory=dict)


class RequestApprovalResponse(BaseModel):
    """Mirrors ``agentfield.client.ApprovalRequestResponse``."""

    approval_request_id: str
    approval_request_url: str = ""


class AwaiterStatusBody(BaseModel):
    status: str  # "waiting" | "running"
    reason: str = ""


# ---------------------------------------------------------------------------
# Notification synthesis helpers
# ---------------------------------------------------------------------------


# Kind → default frontend route. Per-kind overrides happen in
# ``_derive_notification_fields`` below when the payload carries enough
# context (e.g. ``hunt_id`` / ``job_id``) to deep-link.
_DEFAULT_HREF_BY_KIND: dict[str, str] = {
    "clarifying_question": "/start",
    "listings_found": "/compare",
    "approval_needed": "/approve",
    "seller_replied": "/deal",
    "deal_closed": "/deal",
    "error": "/",
    "info": "/",
}


def _derive_notification_fields(
    payload: dict[str, Any], *, approval_request_id: str
) -> dict[str, Any]:
    """Map a reasoner pause-payload onto Notification field values.

    Defensive: payload is arbitrary structured data the reasoner chose to
    include — we look for known keys (``kind``, ``question``, ``draft_text``,
    ``listing_id``, ...) but fall back to sensible defaults for any
    missing field.
    """
    kind = payload.get("kind") if isinstance(payload, dict) else None
    if kind not in (
        "clarifying_question",
        "listings_found",
        "approval_needed",
        "seller_replied",
        "deal_closed",
        "error",
        "info",
    ):
        kind = "approval_needed"

    job_id = payload.get("job_id") if isinstance(payload, dict) else None
    hunt_id = payload.get("hunt_id") if isinstance(payload, dict) else None
    listing_id = payload.get("listing_id") if isinstance(payload, dict) else None

    # ---- title / body per kind ----
    if kind == "clarifying_question":
        question = (payload.get("question") or "").strip()
        title = "We need one quick clarification"
        body = question or "Goti needs a bit more info before searching listings."
    elif kind == "listings_found":
        count = payload.get("count") or payload.get("listing_count")
        title = (
            f"Found {int(count)} listings to compare"
            if isinstance(count, (int, float))
            else "Listings ready for review"
        )
        body = "Pick the listings you want to negotiate on."
    elif kind == "approval_needed":
        draft = (payload.get("draft_text") or "").strip()
        title = "Approve this message before we send"
        body = (draft[:120] + "…") if len(draft) > 120 else (draft or "Goti drafted a reply.")
    elif kind == "seller_replied":
        title = "Seller replied"
        body = (payload.get("reply_text") or "")[:160] or "There's a new seller message."
    elif kind == "deal_closed":
        price = payload.get("agreed_price")
        title = "Deal closed"
        body = (
            f"Agreed at ${price}"
            if isinstance(price, (int, float))
            else "Negotiation concluded."
        )
    elif kind == "error":
        title = "Something went wrong"
        body = (payload.get("error_message") or "An error occurred.")[:240]
    else:
        title = (payload.get("title") or "Goti notification")[:240]
        body = (payload.get("body") or "")[:240]

    # ---- target_href ----
    base = _DEFAULT_HREF_BY_KIND.get(kind, "/")
    target_href = base
    query: list[str] = []
    if hunt_id:
        query.append(f"hunt_id={hunt_id}")
    if job_id and kind in ("seller_replied", "deal_closed"):
        # Per-job deep-links use ``/deal/{job_id}`` (no query string).
        target_href = f"/deal/{job_id}"
        query = []
    elif job_id:
        query.append(f"job_id={job_id}")
    if listing_id and kind == "approval_needed":
        query.append(f"listing_id={listing_id}")
    if kind == "approval_needed":
        # Surface the approval_request_id so the /approve page can preselect
        # the correct ticket without a list scan.
        query.append(f"approval_request_id={approval_request_id}")
    if query:
        target_href = f"{target_href}?{'&'.join(query)}"

    return {
        "kind": kind,
        "title": title,
        "body": body,
        "target_href": target_href,
        "hunt_id": hunt_id,
        "job_id": job_id,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/agents/{node}/executions/{execution_id}/request-approval",
    response_model=RequestApprovalResponse,
)
async def request_approval(
    node: str,
    execution_id: str,
    body: RequestApprovalBody,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RequestApprovalResponse:
    """Receive ``app.pause()`` from a reasoner; emit a user notification.

    Idempotent on ``approval_request_id`` — if the agent retries the
    pause (e.g. after a transient control-plane failure), we update the
    existing queue row rather than creating a duplicate notification.
    """
    _ensure_loopback_origin(request)
    payload = body.payload if isinstance(body.payload, dict) else {}
    # Per-user routing: reasoners MUST include ``user_id`` in payload —
    # there is no demo-user fallback. If the reasoner forgot, we surface
    # a clear 422 so the agent dev sees the contract break.
    target_user = (
        payload.get("user_id") if isinstance(payload, dict) else None
    )
    if not target_user:
        raise HTTPException(
            status_code=422,
            detail=(
                "request-approval payload missing 'user_id'. Reasoners "
                "MUST include user_id in the pause payload so the bridge "
                "can route the notification."
            ),
        )

    # ---- upsert the queue row ----
    existing = await ApprovalQueueItem.get_by_approval_request_id(
        session, body.approval_request_id
    )
    if existing is None:
        # Pull a few fields off the payload (defensive) so the queue row
        # is useful even before the user resolves it.
        draft_text = (
            payload.get("draft_text") if isinstance(payload, dict) else None
        ) or ""
        draft_reasoning = (
            payload.get("draft_reasoning") if isinstance(payload, dict) else None
        )
        job_id = payload.get("job_id") if isinstance(payload, dict) else None
        queue_row = await ApprovalQueueItem.create(
            session,
            job_id=job_id,
            draft_text=str(draft_text),
            draft_reasoning=draft_reasoning,
            execution_id=execution_id,
            agent_node_id=node,
            agent_callback_url=body.callback_url or None,
            approval_request_id=body.approval_request_id,
            request_payload=payload,
        )
    else:
        # Update bridge fields; preserve any draft_text/reasoning that
        # was set by a previous orchestration path.
        existing.execution_id = execution_id
        existing.agent_node_id = node
        if body.callback_url:
            existing.agent_callback_url = body.callback_url
        existing.request_payload = payload
        await session.flush()
        queue_row = existing

    # ---- create the user-facing notification ----
    # Only if one doesn't already exist for this approval_request_id —
    # keeps retries from spamming the user.
    existing_notif = await Notification.get_by_approval_request_id(
        session, body.approval_request_id
    )
    if existing_notif is None:
        fields = _derive_notification_fields(
            payload, approval_request_id=body.approval_request_id
        )
        notif = await Notification.create(
            session,
            user_id=str(target_user),
            kind=fields["kind"],
            title=fields["title"],
            body=fields["body"],
            target_href=fields["target_href"],
            payload=payload,
            hunt_id=fields.get("hunt_id"),
            job_id=fields.get("job_id"),
            approval_request_id=body.approval_request_id,
            status="unread",
        )
        new_event = notif.to_event_dict()
    else:
        new_event = None

    await session.commit()

    # ---- push onto the in-memory queue for SSE delivery ----
    if new_event is not None:
        try:
            delivered = await notif_queue.enqueue(new_event)
            logger.info(
                "request_approval: pushed notification id=%s to %d subscribers",
                new_event["id"],
                delivered,
            )
        except Exception:  # noqa: BLE001 — never block the agent on a queue hiccup
            logger.exception(
                "request_approval: enqueue failed for notification id=%s",
                new_event["id"],
            )

    logger.info(
        "request_approval: node=%s execution_id=%s approval_request_id=%s "
        "callback_url=%s queue_row=%s",
        node,
        execution_id,
        body.approval_request_id,
        body.callback_url or "<none>",
        queue_row.id,
    )

    return RequestApprovalResponse(
        approval_request_id=body.approval_request_id,
        approval_request_url=body.approval_request_url,
    )


@router.post("/agents/{node}/executions/{execution_id}/awaiter-status")
async def awaiter_status(
    node: str,
    execution_id: str,
    body: AwaiterStatusBody,
    request: Request,
) -> dict:
    """No-op acceptance of awaiter-status propagation."""
    _ensure_loopback_origin(request)
    logger.debug(
        "awaiter_status: node=%s execution_id=%s status=%s reason=%s",
        node,
        execution_id,
        body.status,
        body.reason,
    )
    return {"ok": True}


@router.get("/agents/{node}/executions/{execution_id}/approval-status")
async def approval_status(
    node: str,
    execution_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the current approval state for an execution.

    The agent's ``wait_for_resume`` (client.py:1862) uses this as a
    fallback poll. We look up the queue row by ``execution_id`` and map
    our domain decision (``approve`` / ``reject`` / None) to AgentField's
    status vocabulary (``approved`` / ``rejected`` / ``pending``).
    """
    _ensure_loopback_origin(request)
    from sqlalchemy import select

    _ = node  # node is informational; the queue row is keyed on execution_id
    result = await session.execute(
        select(ApprovalQueueItem).where(
            ApprovalQueueItem.execution_id == execution_id
        )
    )
    row: Optional[ApprovalQueueItem] = result.scalar_one_or_none()
    if row is None:
        return {
            "status": "unknown",
            "response": None,
            "request_url": None,
            "requested_at": None,
            "responded_at": None,
        }

    decision_map = {"approve": "approved", "reject": "rejected"}
    status = decision_map.get(row.decision or "", "pending") if row.decision else "pending"

    return {
        "status": status,
        "response": row.feedback,
        "request_url": None,
        "requested_at": row.created_at.isoformat() if row.created_at else None,
        "responded_at": row.decided_at.isoformat() if row.decided_at else None,
    }


# ---------------------------------------------------------------------------
# Node lifecycle endpoints — no-ops that quiet the SDK's chatter
# ---------------------------------------------------------------------------


@router.post("/nodes/register")
async def register_node(body: dict[str, Any], request: Request) -> dict:
    """Accept registration without persisting (no agent registry yet)."""
    _ensure_loopback_origin(request)
    node_id = body.get("id") or body.get("node_id") or "<unknown>"
    logger.info("register_node: accepted node=%s", node_id)
    return {"ok": True, "id": node_id, "status": "registered"}


@router.post("/nodes/{node_id}/heartbeat")
async def heartbeat(node_id: str, request: Request) -> dict:
    """Accept heartbeats silently (logs at DEBUG to avoid noise)."""
    _ensure_loopback_origin(request)
    logger.debug("heartbeat: node=%s", node_id)
    return {"ok": True}


@router.post("/nodes/{node_id}/shutdown")
async def shutdown_node(node_id: str, request: Request) -> dict:
    _ensure_loopback_origin(request)
    logger.info("shutdown_node: accepted node=%s", node_id)
    return {"ok": True}


@router.put("/nodes/{node_id}/health")
async def update_health(
    node_id: str, body: dict[str, Any], request: Request
) -> dict:
    _ensure_loopback_origin(request)
    _ = body
    logger.debug("update_health: node=%s", node_id)
    return {"ok": True}


@router.get("/nodes")
async def list_nodes(request: Request) -> dict:
    """No-op listing endpoint (returns empty)."""
    _ensure_loopback_origin(request)
    return {"nodes": []}


# ---------------------------------------------------------------------------
# Per-execution status (sent by ``agent._post_execution_status``)
# ---------------------------------------------------------------------------


@router.post("/executions/{execution_id}/status")
async def execution_status(
    execution_id: str, body: dict[str, Any], request: Request
) -> dict:
    """Accept post-execution status updates without persisting."""
    _ensure_loopback_origin(request)
    status = body.get("status") if isinstance(body, dict) else None
    logger.debug(
        "execution_status: execution_id=%s status=%s", execution_id, status
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# DID + VC subsystem — no-op accept
#
# AgentField's optional Decentralized Identity layer auto-registers the
# agent's DID + emits Verifiable Credentials for workflows. We don't wire
# any of it; without these endpoints the SDK logs ``DID registration
# request failed: 404`` once at boot. Return 200 so the SDK's startup is
# silent. No persistence — these are no-op accepts.
# ---------------------------------------------------------------------------


@router.post("/did/register")
async def did_register(body: dict[str, Any], request: Request) -> dict:
    """Accept DID registration but disable the subsystem.

    The SDK's flow: HTTP 200 + ``success: True`` → enables the DID
    subsystem (expects an identity_package); ``success: False`` → logs
    a warning + disables. We don't wire DID, so return ``success: False``
    with a clear ``error`` field. The agent runs without DID — exactly
    what we want.
    """
    _ensure_loopback_origin(request)
    logger.debug("did_register: %s", body.get("node_id") if isinstance(body, dict) else "?")
    return {"success": False, "error": "DID subsystem intentionally disabled in this deployment"}


@router.post("/did/verify")
async def did_verify(body: dict[str, Any], request: Request) -> dict:
    _ensure_loopback_origin(request)
    return {"ok": True, "verified": True}


@router.post("/did/export/vcs")
async def did_export_vcs(body: dict[str, Any], request: Request) -> dict:
    _ensure_loopback_origin(request)
    return {"ok": True, "vcs": []}


@router.post("/did/workflow/{workflow_id}/vc")
async def did_workflow_vc(
    workflow_id: str, body: dict[str, Any], request: Request
) -> dict:
    _ensure_loopback_origin(request)
    return {"ok": True, "workflow_id": workflow_id}


@router.get("/did/workflow/{workflow_id}/vc-chain")
async def did_workflow_vc_chain(workflow_id: str, request: Request) -> dict:
    _ensure_loopback_origin(request)
    return {"ok": True, "workflow_id": workflow_id, "vc_chain": []}


# ---------------------------------------------------------------------------
# Memory-events WebSocket — no-op
# ---------------------------------------------------------------------------


@router.websocket("/memory/events/ws")
async def memory_events_ws(websocket: WebSocket) -> None:
    """Accept the memory-events WebSocket and hold it open silently.

    AgentField's ``MemoryEventClient`` (memory_events.py:152) auto-connects
    on agent startup; without a server-side handler that ACCEPTS the
    connection the SDK logs ``HTTP 403`` + reconnects in a tight loop,
    spamming the api logs.

    Unconditional accept-on-loopback contract:
    - We DO NOT call ``_ensure_loopback_origin`` here. WebSocket connect
      requests in Starlette don't follow the same ``request.client.host``
      pattern as HTTP handlers (the HTTP-style 403 raise inside a WS
      handler would surface as ``connection rejected (403 Forbidden)``
      to the SDK rather than a clean close).
    - Instead, we explicitly check ``websocket.client.host`` against the
      loopback set AFTER accepting. Non-loopback peers get closed with
      code 1008 (policy violation); loopback peers stay open.
    - The connection is held open silently — we ``receive_text()`` to
      drain client-sent frames so the peer's send buffer doesn't fill,
      but we never broadcast (no memory-events fan-out yet — BATNA
      shared memory uses direct ``app.memory.get/set`` in v1).

    A real implementation would forward memory-change events to subscribed
    agents; that's out of scope for this Pass.
    """
    # Accept FIRST so the SDK's WebSocket handshake completes cleanly
    # (vs. rejecting at handshake-time which surfaces as 403). Then
    # optionally close non-loopback peers — but in practice this route
    # is only reachable from the co-located agent server on loopback.
    await websocket.accept()
    client = websocket.client
    host = (client.host if client is not None else "") or ""
    if host and host not in _LOOPBACK_HOSTS:
        logger.warning(
            "memory_events_ws: rejecting non-loopback peer host=%s", host
        )
        try:
            await websocket.close(code=1008)
        except Exception:  # noqa: BLE001
            pass
        return

    logger.info("memory_events_ws: accepted connection from %s", websocket.client)
    try:
        while True:
            # Hold the socket open; drain any client-sent frames so the
            # peer's send buffer doesn't fill. No broadcast on our side.
            msg = await websocket.receive_text()
            logger.debug(
                "memory_events_ws: ignored client message: %s", msg[:200]
            )
    except WebSocketDisconnect:
        logger.info("memory_events_ws: peer disconnected")
    except Exception:  # noqa: BLE001 — keep the no-op resilient
        logger.exception("memory_events_ws: socket error")
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Execute submission — used by `agentfield.client._submit_execution_*`
# ---------------------------------------------------------------------------


@router.post("/execute/async/{target}")
async def execute_async(
    target: str, body: dict[str, Any], request: Request
) -> dict:
    """Acknowledge an async execute submission without dispatching.

    The Goti backend invokes reasoners via the simpler
    ``api/orchestration/agents_client.invoke_reasoner`` path
    (``/api/v1/execute/{target}`` proxied to the agent server). The SDK's
    ``client.execute()`` flow is only used by agent-to-agent calls, which
    Goti doesn't exercise. This handler accepts the submission and
    returns a synthetic execution id so the SDK can complete its
    polling loop against the agent server directly.
    """
    _ensure_loopback_origin(request)
    _ = body
    import uuid

    execution_id = f"exec_{uuid.uuid4().hex[:16]}"
    logger.info("execute_async: stub execution_id=%s target=%s", execution_id, target)
    return {
        "execution_id": execution_id,
        "run_id": execution_id,
        "status": "succeeded",
        "result": {},
    }
