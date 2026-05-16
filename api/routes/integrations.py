"""Integrations routes — Actionbook MCP+OAuth (Stream B, Pass 3).

Implements the real Clerk OAuth handshake for linking a user's
Actionbook account:

- ``POST /api/integrations/{provider}/link`` returns the Clerk
  authorize URL with a PKCE challenge; the parked verifier waits in
  ``oauth._PENDING_AUTH`` keyed by ``state``.
- ``GET /api/integrations/{provider}/oauth/callback`` exchanges the
  code for tokens and upserts both shared-provider rows in
  ``integration_accounts``.
- ``GET /api/integrations`` reports per-provider linked status (driven
  by the DB rows).
- ``GET /api/integrations/actionbook/tools`` is an admin / discovery
  helper that lists the MCP server's actual tool surface — extremely
  useful after the first real OAuth so the dev can wire the correct
  tool name into ``client.send_message``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.contracts import IntegrationAccount, LinkInitResponse, OAuthCallbackResponse
from api.db import get_session
from api.integrations.actionbook import client as ab_client, oauth as ab_oauth
from api.models import IntegrationAccountRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

_SUPPORTED_PROVIDERS = {"fb", "nextdoor"}


def _check_provider(provider: str) -> None:
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported provider: {provider!r} (expected 'fb' or 'nextdoor')",
        )


@router.post("/{provider}/link", response_model=LinkInitResponse)
async def link_integration(provider: str) -> LinkInitResponse:
    _check_provider(provider)
    settings = get_settings()
    try:
        return await ab_oauth.begin_oauth(
            user_id=settings.demo_user_id, provider=provider
        )
    except Exception as exc:  # noqa: BLE001 — surface dynamic-registration failures clearly
        logger.exception("link_integration: begin_oauth failed for provider=%s", provider)
        raise HTTPException(
            status_code=502,
            detail=f"failed to begin OAuth: {exc!s}",
        ) from exc


@router.get("/{provider}/oauth/callback", response_model=OAuthCallbackResponse)
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
) -> OAuthCallbackResponse:
    _check_provider(provider)
    try:
        return await ab_oauth.complete_oauth(code=code, state=state, db=session)
    except RuntimeError as exc:
        # state-not-found / token-response-missing-fields — caller error or expired flow.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — upstream HTTP failure
        logger.exception("oauth_callback: complete_oauth failed")
        raise HTTPException(
            status_code=502,
            detail=f"failed to complete OAuth: {exc!s}",
        ) from exc


@router.get("", response_model=list[IntegrationAccount])
async def list_integrations(
    session: AsyncSession = Depends(get_session),
) -> list[IntegrationAccount]:
    settings = get_settings()
    rows = await IntegrationAccountRow.list_active_for_user(
        session, settings.demo_user_id
    )
    linked_by_provider: dict[str, IntegrationAccountRow] = {
        row.provider: row for row in rows
    }
    return [
        IntegrationAccount(
            provider=provider,  # type: ignore[arg-type]
            linked=provider in linked_by_provider,
            linked_at=(
                linked_by_provider[provider].linked_at
                if provider in linked_by_provider
                else None
            ),
        )
        for provider in ("fb", "nextdoor")
    ]


@router.get("/actionbook/tools")
async def list_actionbook_tools(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Discovery helper — returns the MCP server's tools/list response.

    Use after first OAuth to learn the exact tool names Actionbook
    exposes so ``client.send_message`` can be wired to the correct one.
    Returns 412 if no active integration exists yet.
    """
    settings = get_settings()
    try:
        tools = await ab_client.user_list_tools(settings.demo_user_id, session)
    except RuntimeError as exc:
        # oauth.get_valid_access_token raises RuntimeError when no active link.
        raise HTTPException(
            status_code=412,
            detail=(
                "no active Actionbook integration — POST /api/integrations/fb/link "
                "first, complete the OAuth flow, then retry. inner: " + str(exc)
            ),
        ) from exc
    except Exception as exc:  # noqa: BLE001 — bubble upstream MCP failures
        logger.exception("list_actionbook_tools: MCP call failed")
        raise HTTPException(
            status_code=502, detail=f"MCP tools/list failed: {exc!s}"
        ) from exc

    return {"tools": tools}
