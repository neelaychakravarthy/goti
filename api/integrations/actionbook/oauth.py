"""Clerk OAuth flow for the Actionbook MCP integration (Stream B).

Implements the authorization-code-with-PKCE flow against Clerk
(``https://clerk.actionbook.dev``), which is the OAuth issuer fronting the
Actionbook MCP server at ``https://edge.actionbook.dev/mcp``.

The flow at a glance:

1.  First request to ``POST /api/integrations/{provider}/link``:
    - ``get_or_register_client_id()`` ensures we have an OAuth client_id
      (dynamic client registration via RFC 7591 if not pre-configured).
    - ``begin_oauth()`` generates ``state`` + ``code_verifier``, builds the
      Clerk authorize URL, and parks the verifier in an in-memory dict
      keyed by ``state`` (5-min TTL).
    - Returns a ``LinkInitResponse`` the route hands back to the client.

2.  Browser redirects to ``GET /api/integrations/{provider}/oauth/callback``:
    - ``complete_oauth()`` looks up the verifier by ``state``, POSTs to
      Clerk's token endpoint with ``grant_type=authorization_code +
      code_verifier``, and upserts the resulting tokens into
      ``integration_accounts``. Per the SPEC "shared OAuth" decision,
      BOTH ``fb`` and ``nextdoor`` are marked active on a single grant.

3.  Negotiator path needs a valid access token:
    - ``get_valid_access_token()`` reads the user's most recent active
      integration account, refreshes via ``refresh_token`` if needed,
      and returns the access token to the MCP client.

PKCE: S256-only (the Clerk metadata advertises ``["S256"]`` as the only
supported challenge method). The ``_pkce_challenge()`` helper computes
``base64url(sha256(code_verifier))`` with padding stripped, per RFC 7636.

Dynamic Client Registration cache: the registered client_id lives in a
module-level global for the process lifetime — Clerk supports
re-registration cheaply enough that container restarts are acceptable.
An optional env override (``ACTIONBOOK_OAUTH_REGISTERED_CLIENT_ID``)
short-circuits the dance for deployments that want stable credentials.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.contracts import LinkInitResponse, OAuthCallbackResponse
from api.models import IntegrationAccountRow

logger = logging.getLogger(__name__)


# Scopes Goti requests (offline_access required for refresh_token issuance).
OAUTH_SCOPES = "openid profile email offline_access"

# Both marketplaces share a single Clerk grant — granting Actionbook access
# implicitly enables both FB and Nextdoor automation per the SPEC.
_SHARED_PROVIDERS: tuple[str, ...] = ("fb", "nextdoor")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_REGISTERED_CLIENT_ID: str | None = None
_REGISTRATION_LOCK: asyncio.Lock = asyncio.Lock()

# state -> {"code_verifier", "user_id", "provider", "created_at"}
_PENDING_AUTH: dict[str, dict[str, Any]] = {}
_PENDING_AUTH_TTL_SECONDS: int = 300


# ---------------------------------------------------------------------------
# PKCE + helpers
# ---------------------------------------------------------------------------


def _pkce_challenge(code_verifier: str) -> str:
    """RFC 7636 ``S256`` code_challenge: base64url(sha256(verifier)) sans padding."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _callback_url_for(provider: str) -> str:
    """Interpolate ``{provider}`` in the configured redirect URI template."""
    settings = get_settings()
    template = settings.actionbook_oauth_redirect_uri or ""
    return template.replace("{provider}", provider)


def _all_callback_urls() -> list[str]:
    """Both provider callback URLs — registered together so either side works."""
    return [_callback_url_for(p) for p in _SHARED_PROVIDERS]


def _gc_pending_auth() -> None:
    """Evict in-memory pending-auth entries older than the TTL."""
    cutoff = time.time() - _PENDING_AUTH_TTL_SECONDS
    stale = [k for k, v in _PENDING_AUTH.items() if v.get("created_at", 0) < cutoff]
    for k in stale:
        _PENDING_AUTH.pop(k, None)
    if stale:
        logger.debug("oauth: gc evicted %d stale state(s)", len(stale))


# ---------------------------------------------------------------------------
# Dynamic Client Registration
# ---------------------------------------------------------------------------


async def get_or_register_client_id() -> str:
    """Return a Clerk OAuth client_id, registering one if needed.

    Resolution order:
    1.  Env override ``ACTIONBOOK_OAUTH_REGISTERED_CLIENT_ID`` (if set).
    2.  Module-level cache populated by a prior registration.
    3.  Fresh ``POST {issuer}/oauth/register`` (RFC 7591).

    Concurrency: a single ``asyncio.Lock`` serializes the
    register-if-needed branch so two simultaneous link requests don't
    double-register.
    """
    global _REGISTERED_CLIENT_ID

    settings = get_settings()
    override = settings.actionbook_oauth_registered_client_id
    if override:
        return override

    if _REGISTERED_CLIENT_ID is not None:
        return _REGISTERED_CLIENT_ID

    async with _REGISTRATION_LOCK:
        if _REGISTERED_CLIENT_ID is not None:  # double-checked locking
            return _REGISTERED_CLIENT_ID

        register_url = f"{settings.actionbook_oauth_issuer.rstrip('/')}/oauth/register"
        registration_payload = {
            "client_name": "Goti",
            "redirect_uris": _all_callback_urls(),
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": OAUTH_SCOPES,
            "application_type": "web",
        }
        logger.info(
            "oauth: dynamic-registering OAuth client with %s redirect_uris=%s",
            register_url,
            registration_payload["redirect_uris"],
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(register_url, json=registration_payload)
            response.raise_for_status()
            data = response.json()

        client_id = data.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise RuntimeError(
                f"oauth: dynamic registration response missing client_id: {data!r}"
            )
        _REGISTERED_CLIENT_ID = client_id
        logger.info("oauth: dynamic registration succeeded; client_id=%s", client_id)
        return client_id


# ---------------------------------------------------------------------------
# begin_oauth — build authorize URL + park PKCE verifier
# ---------------------------------------------------------------------------


async def begin_oauth(user_id: str, provider: str) -> LinkInitResponse:
    """Start the OAuth dance for ``user_id`` + ``provider``.

    Generates ``state`` + ``code_verifier``, computes ``code_challenge``,
    builds the Clerk authorize URL with PKCE + scope params, parks the
    verifier in ``_PENDING_AUTH``, and returns the URL for the caller to
    redirect the user to.
    """
    settings = get_settings()
    client_id = await get_or_register_client_id()

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _pkce_challenge(code_verifier)

    redirect_uri = _callback_url_for(provider)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = (
        f"{settings.actionbook_oauth_issuer.rstrip('/')}/oauth/authorize"
        f"?{urlencode(params)}"
    )

    _gc_pending_auth()
    _PENDING_AUTH[state] = {
        "code_verifier": code_verifier,
        "user_id": user_id,
        "provider": provider,
        "redirect_uri": redirect_uri,
        "created_at": time.time(),
    }

    return LinkInitResponse(
        authorize_url=authorize_url,
        state=state,
        provider=provider,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# complete_oauth — token exchange + DB upsert
# ---------------------------------------------------------------------------


async def complete_oauth(
    code: str, state: str, db: AsyncSession
) -> OAuthCallbackResponse:
    """Exchange ``code`` for tokens; persist to ``integration_accounts``.

    Marks BOTH ``fb`` and ``nextdoor`` linked (one Clerk grant covers
    Actionbook's internal Facebook + Nextdoor session per the SPEC's
    "shared OAuth" decision).
    """
    _gc_pending_auth()
    entry = _PENDING_AUTH.pop(state, None)
    if entry is None:
        raise RuntimeError("oauth: state not found or expired")

    settings = get_settings()
    client_id = await get_or_register_client_id()
    token_url = f"{settings.actionbook_oauth_issuer.rstrip('/')}/oauth/token"

    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": entry["redirect_uri"],
        "client_id": client_id,
        "code_verifier": entry["code_verifier"],
    }
    logger.info("oauth: exchanging code at %s", token_url)
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            token_url,
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        token_response = response.json()

    access_token = token_response.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(
            f"oauth: token response missing access_token: keys={list(token_response.keys())}"
        )
    refresh_token = token_response.get("refresh_token")
    expires_in = token_response.get("expires_in")
    scope = token_response.get("scope")

    token_expires_at: datetime | None = None
    if isinstance(expires_in, (int, float)):
        token_expires_at = datetime.now(tz=timezone.utc) + timedelta(
            seconds=float(expires_in)
        )

    # Per "shared OAuth" decision: one grant -> both providers active.
    now = datetime.now(tz=timezone.utc)
    for provider in _SHARED_PROVIDERS:
        await IntegrationAccountRow.upsert(
            db,
            user_id=entry["user_id"],
            provider=provider,
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            token_expires_at=token_expires_at,
            scopes=scope if isinstance(scope, str) else None,
            linked_at=now,
            status="active",
        )
    await db.commit()

    return OAuthCallbackResponse(
        linked=True,
        provider=entry["provider"],  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Token refresh + read-side helper
# ---------------------------------------------------------------------------


async def _refresh_access_token(
    row: IntegrationAccountRow, db: AsyncSession
) -> IntegrationAccountRow:
    """POST to the token endpoint with ``grant_type=refresh_token``.

    Persists the new tokens back to ``integration_accounts`` (across both
    shared-OAuth provider rows) and returns the refreshed row for the
    caller's provider.
    """
    if not row.refresh_token:
        raise RuntimeError(
            "oauth: no refresh_token stored for user="
            f"{row.user_id} provider={row.provider}"
        )

    settings = get_settings()
    client_id = await get_or_register_client_id()
    token_url = f"{settings.actionbook_oauth_issuer.rstrip('/')}/oauth/token"

    refresh_payload = {
        "grant_type": "refresh_token",
        "refresh_token": row.refresh_token,
        "client_id": client_id,
    }
    logger.info(
        "oauth: refreshing token for user=%s provider=%s", row.user_id, row.provider
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            token_url,
            data=refresh_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        token_response = response.json()

    new_access_token = token_response.get("access_token")
    if not isinstance(new_access_token, str) or not new_access_token:
        raise RuntimeError(
            f"oauth: refresh response missing access_token: keys={list(token_response.keys())}"
        )
    new_refresh_token = token_response.get("refresh_token") or row.refresh_token
    expires_in = token_response.get("expires_in")
    scope = token_response.get("scope") or row.scopes

    new_expires_at: datetime | None = None
    if isinstance(expires_in, (int, float)):
        new_expires_at = datetime.now(tz=timezone.utc) + timedelta(
            seconds=float(expires_in)
        )

    for provider in _SHARED_PROVIDERS:
        await IntegrationAccountRow.upsert(
            db,
            user_id=row.user_id,
            provider=provider,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_expires_at=new_expires_at,
            scopes=scope,
            linked_at=row.linked_at,
            status="active",
        )
    await db.commit()

    refreshed = await IntegrationAccountRow.get(db, row.user_id, row.provider)
    if refreshed is None:  # pragma: no cover — should never happen
        raise RuntimeError(
            f"oauth: refreshed row vanished for user={row.user_id} provider={row.provider}"
        )
    return refreshed


async def get_valid_access_token(
    user_id: str, db: AsyncSession, provider: str = "fb"
) -> str:
    """Return a valid (refresh-on-stale) access_token for ``user_id``.

    Raises ``RuntimeError`` if no active link exists or refresh fails —
    callers decide how to surface (the MCP client returns a clear 412 to
    the route layer).
    """
    row = await IntegrationAccountRow.get(db, user_id, provider)
    if row is None or row.status != "active":
        raise RuntimeError(
            f"oauth: no active integration_account for user={user_id} provider={provider}"
        )

    # Refresh if expired or within 60s of expiry (small buffer for clock skew).
    if row.token_expires_at is not None:
        deadline = datetime.now(tz=timezone.utc) + timedelta(seconds=60)
        if row.token_expires_at <= deadline:
            row = await _refresh_access_token(row, db)

    return row.access_token
