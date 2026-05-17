"""Thin httpx wrapper for invoking AgentField reasoners over HTTP.

All reasoners (clarifier, valuation, negotiator, coordinator,
picker, classifier) live on a single shared Agent with ``node_id="goti"``.
The af-server execute URL format is::

    {AF_AGENT_SERVER_URL}/api/v1/execute/goti.<method>

NB: this is the **agent server URL** (port 8080), NOT the control plane
URL (port 8000 / FastAPI). The control plane URL is where AgentField's
SDK posts BACK to FastAPI for pause/resume/heartbeats; the agent server
URL is where FastAPI POSTs IN to invoke reasoners. Confusing them
results in 404s on every reasoner call.

Reasoner responses are wrapped under either ``output`` or ``result`` (the
exact envelope depends on af-server version); this module unwraps both
shapes defensively and surfaces a clean dict to the caller.

Callers (in `api/routes/*` and `api/orchestration/*`) use
``invoke_reasoner(method, input)`` rather than re-inlining httpx.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from api.config import get_settings

logger = logging.getLogger(__name__)

# Shared Agent node_id. All reasoners are registered on the same Agent
# instance and addressed via ``goti.<method>`` against agentfield 0.1.84.
AGENT_NODE_ID = "goti"


def _execute_url(method: str) -> str:
    """Build the agent server execute URL for ``<method>``.

    Reads ``af_agent_server_url`` (default ``http://localhost:8080``).

    AgentField 0.1.84 registers ``@app.reasoner()`` functions at
    ``POST /reasoners/{name}`` on the agent server (see
    ``agentfield/agent.py:1775``: ``endpoint_path = f"/reasoners/{reasoner_id}"``).
    A previous version of this module guessed
    ``/api/v1/execute/{node_id}.{method}`` which 404s on every call —
    that's what was silently cancelling every Job created via Start
    Negotiation. Confirmed by hitting the live server: only ``/reasoners/<name>``
    returns 200.
    """
    settings = get_settings()
    return (
        f"{settings.af_agent_server_url.rstrip('/')}"
        f"/reasoners/{method}"
    )


def _unwrap(data: Any) -> dict:
    """Unwrap an af-server response envelope to the inner reasoner dict.

    Handles ``{"output": {...}}``, ``{"result": {...}}``, and bare-dict
    responses. Returns ``{}`` on shapes we don't recognize so the caller
    can detect "no useful output" via key absence.
    """
    if not isinstance(data, dict):
        return {}
    body = data.get("output")
    if not isinstance(body, dict):
        body = data.get("result")
    if not isinstance(body, dict):
        body = data
    return body if isinstance(body, dict) else {}


async def invoke_reasoner(
    method: str,
    input: dict,
    *,
    timeout: float = 60.0,
    raise_on_error: bool = True,
) -> dict:
    """Forward a reasoner invocation to the AgentField control plane.

    Args:
        method: Reasoner method name (e.g. ``"draft_message"``).
        input: Reasoner input payload — wrapped in ``{"input": ...}`` per
            the af-server execute contract.
        timeout: httpx total timeout.
        raise_on_error: If True (default), an httpx transport error or an
            ``{"error": ...}`` reasoner response raises ``HTTPException
            (502)``. If False, the inner dict (possibly with an ``error``
            key) is returned to the caller.

    Returns:
        The unwrapped reasoner output dict.
    """
    url = _execute_url(method)
    # AgentField 0.1.84 reasoner endpoints expect the input fields
    # directly at the top level of the JSON body — NOT wrapped in
    # ``{"input": {...}}``. The earlier wrapped shape produces 422.
    # Verified against ``agentfield/agent.py:1808-1845`` which calls
    # ``_validate_handler_input(body, handler_input_fields)`` directly
    # on the parsed body.
    payload = dict(input)
    logger.info("invoke_reasoner: forwarding to %s payload_keys=%s", url, list(input.keys()))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.exception("invoke_reasoner: HTTP error calling %s", url)
        if raise_on_error:
            raise HTTPException(
                status_code=502,
                detail=f"AgentField reasoner call failed: {exc!s}",
            ) from exc
        return {"error": str(exc)}

    body = _unwrap(data)
    if "error" in body and raise_on_error:
        raise HTTPException(status_code=502, detail=str(body["error"]))
    return body


async def spawn_reasoner(method: str, input: dict, *, timeout: float = 5.0) -> None:
    """Fire-and-forget reasoner invocation.

    Used when the caller doesn't want to await the reasoner (e.g. the
    negotiator pauses internally via app.pause() so awaiting would block
    until the user approves). Logs and swallows transport failures.

    NB: with the negotiator-returns-draft-directly workaround (see
    `api/orchestration/jobs.py` docstring), this helper is currently
    unused — but kept for symmetry / future use.
    """
    url = _execute_url(method)
    payload = dict(input)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.post(url, json=payload)
    except httpx.HTTPError:
        logger.exception("spawn_reasoner: fire-and-forget call failed for %s", method)
