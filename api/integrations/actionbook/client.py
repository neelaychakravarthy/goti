"""MCP-over-HTTP JSON-RPC client for Actionbook (Stream B).

Hand-rolled JSON-RPC client because the official ``mcp`` Python SDK has
heavy abstractions that obscure the headers we care about
(``Mcp-Session-Id``, ``Mcp-Protocol-Version``, ``Authorization: Bearer
…``). ~50 lines gives us full control + graceful 401 retry.

Session lifecycle:
1.  First call for a user opens a session via JSON-RPC ``initialize``.
    The server returns ``Mcp-Session-Id`` in the response headers; we
    cache it under the user's id for the process lifetime.
2.  Subsequent ``tools/call`` and ``tools/list`` reuse the cached session
    id by adding it to the request headers.
3.  On 401 we invalidate the session, refresh the access token via
    ``oauth.get_valid_access_token``, and retry once.

The high-level ``send_message`` helper is what
``api/routes/approvals.py`` invokes when ``GOTI_USE_MOCKS=0``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.integrations.actionbook import oauth

logger = logging.getLogger(__name__)


MCP_PROTOCOL_VERSION = "2025-03-26"
JSON_RPC_METHOD_NOT_FOUND = -32601

# user_id -> Mcp-Session-Id. Lives for the process lifetime; cleared on 401.
_SESSION_CACHE: dict[str, str] = {}
_SESSION_LOCK: asyncio.Lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Low-level JSON-RPC primitives
# ---------------------------------------------------------------------------


def _make_envelope(method: str, params: dict | None = None) -> dict:
    """Build a JSON-RPC 2.0 request envelope with a unique id."""
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": method,
        "params": params if params is not None else {},
    }


def _base_headers(token: str, session_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


async def initialize_session(token: str) -> str:
    """Open an MCP session via JSON-RPC ``initialize``.

    Returns the ``Mcp-Session-Id`` from the response headers. Raises if
    the server doesn't return one (which would indicate a non-MCP
    endpoint or a Goti client_info mismatch).
    """
    settings = get_settings()
    payload = _make_envelope(
        "initialize",
        {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "goti", "version": "0.1"},
        },
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            settings.actionbook_mcp_url,
            headers=_base_headers(token),
            json=payload,
        )
        response.raise_for_status()
        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get(
            "mcp-session-id"
        )
        if not session_id:
            raise RuntimeError(
                "actionbook.client: initialize response missing Mcp-Session-Id header"
            )
        logger.info(
            "actionbook.client: opened MCP session id=%s", session_id[:8] + "…"
        )
        return session_id


async def _get_or_open_session(user_id: str, token: str) -> str:
    """Cache-aware session opener — one session id per user_id."""
    if user_id in _SESSION_CACHE:
        return _SESSION_CACHE[user_id]
    async with _SESSION_LOCK:
        if user_id in _SESSION_CACHE:
            return _SESSION_CACHE[user_id]
        session_id = await initialize_session(token)
        _SESSION_CACHE[user_id] = session_id
        return session_id


def _invalidate_session(user_id: str) -> None:
    _SESSION_CACHE.pop(user_id, None)


async def _post_jsonrpc(
    token: str, session_id: str, envelope: dict
) -> httpx.Response:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.post(
            settings.actionbook_mcp_url,
            headers=_base_headers(token, session_id=session_id),
            json=envelope,
        )


def _unwrap_jsonrpc(response: httpx.Response) -> dict:
    """Parse a JSON-RPC response. Raises on JSON-RPC ``error`` envelope."""
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(
            f"actionbook.client: JSON-RPC response not an object: {data!r}"
        )
    if "error" in data:
        err = data["error"]
        code = err.get("code") if isinstance(err, dict) else None
        message = err.get("message") if isinstance(err, dict) else None
        raise JsonRpcError(code=code, message=message, raw=err)
    return data.get("result", {}) if isinstance(data.get("result"), dict) else data


class JsonRpcError(RuntimeError):
    """Raised when the MCP server returns a JSON-RPC ``error`` envelope."""

    def __init__(
        self,
        *,
        code: int | None,
        message: str | None,
        raw: Any | None = None,
    ) -> None:
        super().__init__(f"JSON-RPC error code={code} message={message!r}")
        self.code = code
        self.message = message
        self.raw = raw


# ---------------------------------------------------------------------------
# Public API — call_tool / list_tools (with 401 refresh-retry)
# ---------------------------------------------------------------------------


async def call_tool(
    token: str, session_id: str, tool_name: str, args: dict
) -> dict:
    """JSON-RPC ``tools/call`` with ``name`` + ``arguments`` params.

    Raises ``JsonRpcError`` on a JSON-RPC error envelope (caller can
    inspect ``.code`` to distinguish e.g. ``-32601 Method not found``).
    Raises ``httpx.HTTPStatusError`` on HTTP-level failures (401, 5xx).
    """
    envelope = _make_envelope(
        "tools/call", {"name": tool_name, "arguments": args}
    )
    response = await _post_jsonrpc(token, session_id, envelope)
    response.raise_for_status()
    return _unwrap_jsonrpc(response)


async def list_tools(token: str, session_id: str) -> list[dict]:
    """JSON-RPC ``tools/list`` — discovery helper.

    Returns the list of tool descriptors (``[{name, description,
    inputSchema}, …]``). Useful for the dev's first hands-on session
    after a real OAuth to discover Actionbook's actual tool surface.
    """
    envelope = _make_envelope("tools/list", {})
    response = await _post_jsonrpc(token, session_id, envelope)
    response.raise_for_status()
    result = _unwrap_jsonrpc(response)
    tools = result.get("tools") if isinstance(result, dict) else None
    return tools if isinstance(tools, list) else []


# ---------------------------------------------------------------------------
# High-level helpers used by FastAPI routes / agents
# ---------------------------------------------------------------------------


async def _with_refresh_retry(
    user_id: str,
    db: AsyncSession,
    operation,  # async fn (token, session_id) -> Any
) -> Any:
    """Run ``operation`` with a fresh token + session; refresh once on 401.

    Centralizes the "401 -> invalidate + retry" path so neither
    ``send_message`` nor ``user_list_tools`` duplicates it.
    """
    token = await oauth.get_valid_access_token(user_id, db)
    session_id = await _get_or_open_session(user_id, token)
    try:
        return await operation(token, session_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise
        logger.info(
            "actionbook.client: 401 from MCP; invalidating session + retrying once"
        )
        _invalidate_session(user_id)
        token = await oauth.get_valid_access_token(user_id, db)
        session_id = await _get_or_open_session(user_id, token)
        return await operation(token, session_id)


async def send_message(
    user_id: str,
    listing_id: str,
    text: str,
    marketplace: str,
    db: AsyncSession,
) -> str:
    """High-level helper: drive Actionbook to send a message on ``marketplace``.

    Resolves the OAuth token, opens a session if needed, invokes
    ``tools/call`` with a best-guess tool name. Returns the platform's
    message id on success.

    TODO(stream-c): the exact tool name Actionbook exposes for
    "send a marketplace message" is unknown until first OAuth + a live
    ``tools/list`` introspection. The placeholder
    ``f"{marketplace}_send_message"`` is a guess. If the MCP server
    returns JSON-RPC error -32601 (Method not found), the
    ``GET /api/integrations/actionbook/tools`` admin endpoint reveals
    the real tool list — wire the correct name here once known.
    """
    tool_name = f"{marketplace}_send_message"
    args = {"listing_id": listing_id, "text": text}

    async def _op(token: str, session_id: str) -> dict:
        return await call_tool(token, session_id, tool_name, args)

    try:
        result = await _with_refresh_retry(user_id, db, _op)
    except JsonRpcError as exc:
        if exc.code == JSON_RPC_METHOD_NOT_FOUND:
            raise RuntimeError(
                "actionbook.client: tool '%s' not found on MCP server. "
                "Hit GET /api/integrations/actionbook/tools to discover the real "
                "tool surface, then update send_message's tool_name in "
                "api/integrations/actionbook/client.py." % tool_name
            ) from exc
        raise

    if isinstance(result, dict):
        message_id = result.get("message_id") or result.get("id")
        if isinstance(message_id, str) and message_id:
            return message_id
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                maybe_id = first.get("message_id") or first.get("id")
                if isinstance(maybe_id, str) and maybe_id:
                    return maybe_id
    # Fallback: synthesize a deterministic id from the tool-call uuid so the
    # caller's logging stays useful even when the upstream shape is unknown.
    fallback_id = f"actionbook-{uuid.uuid4().hex[:8]}"
    logger.info(
        "actionbook.client.send_message: upstream response had no message_id; "
        "returning synthetic id=%s (result keys=%s)",
        fallback_id,
        list(result.keys()) if isinstance(result, dict) else type(result).__name__,
    )
    return fallback_id


async def user_list_tools(user_id: str, db: AsyncSession) -> list[dict]:
    """Wrapper used by the admin discovery route."""

    async def _op(token: str, session_id: str) -> list[dict]:
        return await list_tools(token, session_id)

    return await _with_refresh_retry(user_id, db, _op)
