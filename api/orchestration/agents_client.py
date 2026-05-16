"""Thin httpx wrapper for invoking AgentField reasoners over HTTP.

Per Pass 1's empirical verification, all four reasoners (clarifier,
valuation, negotiator, coordinator) live on a single shared Agent with
``node_id="goti"``. The af-server execute URL format is::

    {AF_CONTROL_PLANE_URL}/api/v1/execute/goti.<method>

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

# Shared Agent node_id (renamed from "goti-clarifier" in Pass 1 — verified
# at runtime against agentfield 0.1.84).
AGENT_NODE_ID = "goti"


def _execute_url(method: str) -> str:
    settings = get_settings()
    return (
        f"{settings.af_control_plane_url.rstrip('/')}"
        f"/api/v1/execute/{AGENT_NODE_ID}.{method}"
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
    payload = {"input": input}
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
    payload = {"input": input}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.post(url, json=payload)
    except httpx.HTTPError:
        logger.exception("spawn_reasoner: fire-and-forget call failed for %s", method)
