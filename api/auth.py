"""Google OAuth ID-token verification + FastAPI dependencies.

The frontend (NextAuth Google provider) signs the user in via Google
and stores the Google ID token in the session. Every API request
includes ``Authorization: Bearer <id_token>`` (or for SSE, ``?token=...``
since EventSource can't set headers). This module verifies that token
against Google's JWKS using the ``google-auth`` library, resolves to
a real ``User`` row (upserting on first sign-in), and exposes the
``current_user`` / ``optional_current_user`` dependencies the routes
use to gate access.

Verification details:

- ``audience`` is the configured ``GOOGLE_OAUTH_CLIENT_ID`` — the same
  client_id the frontend's NextAuth provider uses. Mismatched audience
  means the token was issued for a different client.
- ``clock_skew_in_seconds`` is 10s to tolerate small clock drift
  between Goti and Google (and between Vercel / Zeabur if deployed
  split).
- On any verification failure, ``current_user`` raises 401 with the
  underlying reason; ``optional_current_user`` returns None instead.

The ``X-Forwarded-For`` / ``client.host`` loopback check for internal
bridge routes (AgentField → ``/api/v1/...``) is intentionally NOT here
— that's enforced per-route in ``api/routes/agent_bridge.py`` so
unauthenticated reasoners can still call back into FastAPI.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.db import get_session
from api.models import User

logger = logging.getLogger(__name__)


def _lazy_google_imports():
    """Import google-auth lazily so a missing dep doesn't crash module load.

    Keeps the import surface tidy for tests that monkeypatch
    ``verify_google_id_token`` outright — they don't need the
    google-auth package installed.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token, google_requests


async def verify_google_id_token(token: str) -> dict:
    """Verify a Google ID token. Returns the verified claims dict on success.

    Raises ``HTTPException(401)`` on any verification failure (expired,
    bad signature, audience mismatch, malformed). The detail string
    surfaces the underlying error for debugging without leaking
    secrets.
    """
    settings = get_settings()
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=500,
            detail=(
                "GOOGLE_OAUTH_CLIENT_ID is not configured on the backend; "
                "set it in the API environment to match the frontend's "
                "NextAuth Google provider client_id."
            ),
        )

    try:
        id_token, google_requests = _lazy_google_imports()
    except Exception as exc:  # noqa: BLE001 — surface install errors clearly
        logger.exception("verify_google_id_token: google-auth import failed")
        raise HTTPException(
            status_code=500,
            detail=f"google-auth not installed: {exc!s}",
        ) from exc

    try:
        request = google_requests.Request()
        claims = id_token.verify_oauth2_token(
            token,
            request,
            audience=settings.google_oauth_client_id,
            clock_skew_in_seconds=10,
        )
    except ValueError as exc:
        # google-auth raises ValueError for ALL verification failures —
        # expired, audience mismatch, bad signature, etc. Map to 401.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google ID token: {exc!s}",
        ) from exc

    if not isinstance(claims, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google ID token verification returned non-dict claims.",
        )
    return claims


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Pull the bearer token out of an ``Authorization`` header value.

    Returns None when the header is missing or not in the ``Bearer X``
    shape — callers decide whether to raise 401 or fall through.
    """
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def current_user(
    authorization: Optional[str] = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: resolve the request's bearer token to a User row.

    Raises ``HTTPException(401)`` on missing / malformed / invalid
    token. Verified tokens are upserted into the ``users`` table on
    every request (cheap — keyed on ``google_sub`` and only updates
    ``email`` / ``name`` / ``picture`` if changed).
    """
    token = _extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected 'Bearer <google_id_token>'.",
        )
    claims = await verify_google_id_token(token)
    user = await User.upsert_from_google(session, claims)
    await session.commit()
    await session.refresh(user)
    return user


async def optional_current_user(
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Optional[User]:
    """Variant of ``current_user`` for SSE / public endpoints.

    Reads the token from the ``Authorization`` header OR the ``token``
    query param (used by EventSource which can't set headers). Returns
    None on any failure rather than raising — callers that need a user
    must check for None.
    """
    bearer = _extract_bearer_token(authorization)
    raw_token = bearer or token
    if not raw_token:
        return None
    try:
        claims = await verify_google_id_token(raw_token)
        user = await User.upsert_from_google(session, claims)
        await session.commit()
        await session.refresh(user)
        return user
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001 — never raise from the optional path
        logger.exception("optional_current_user: token verification failed")
        return None
