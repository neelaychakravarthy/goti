"""Integrations routes — Browserbase Contexts.

Goti owns a single ``BROWSERBASE_API_KEY`` + ``BROWSERBASE_PROJECT_ID``;
each Goti user gets one Browserbase Context provisioned via
``bb.contexts.create``. The 2-stage link flow:

1.  ``POST /api/integrations/{provider}/link`` — backend reuses the
    user's existing Browserbase Context (or creates one), mints a
    Live View session pre-navigated to that provider's login URL with
    ``keep_alive=True``, persists the session id, and returns the Live
    View URL. Frontend opens it in a new tab.
2.  ``POST /api/integrations/{provider}/finish`` — user clicks "I'm
    done" in the UI after signing into that one marketplace inside the
    Live View. Backend:
      (a) releases the kept-alive Live View session
          (``bb.end_session``) so it doesn't idle until Browserbase
          times it out;
      (b) runs a quick login-validation roundtrip
          (``bb.validate_login``) — a headless session navigates to a
          per-marketplace "logged-in only" URL and checks whether the
          marketplace bounced us back to a login page;
      (c) flips the row to ``status="active"`` on validation success,
          leaves it ``pending`` (returning ``validated=false``) when the
          probe says the user isn't actually signed in.

``GET /api/integrations`` reports per-provider linked status (one row
per supported marketplace).
``POST /api/integrations/{provider}/unlink`` deletes the local row,
ends any kept-alive Live View session, and best-effort deletes the
upstream Context only when the deleted row was the last remaining
link for the user (the Context is shared across marketplaces).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import current_user
from api.contracts import IntegrationAccount, LinkInitResponse
from api.db import get_session
from api.integrations.browserbase import client as bb_client
from api.integrations.browserbase.client import (
    BrowserbaseQuotaExhausted,
    _MARKETPLACE_LOGIN_URLS,
)


_QUOTA_DETAIL = (
    "Browserbase free tier monthly minutes exhausted. Upgrade your plan "
    "at https://browserbase.com/plans or wait for the monthly reset."
)
from api.models import IntegrationAccountRow, User
from api.rate_limit import limit as _rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

_SUPPORTED_PROVIDERS = {"fb", "nextdoor", "offerup", "craigslist"}


def _check_provider(provider: str) -> None:
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unsupported provider: {provider!r} "
                "(expected one of 'fb', 'nextdoor', 'offerup', 'craigslist')"
            ),
        )


@router.post("/{provider}/link", response_model=LinkInitResponse)
@_rate_limit("5/minute")
async def link_integration(
    request: Request,
    provider: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> LinkInitResponse:
    """Stage 1 of the Browserbase Context link flow.

    If the user already has an active link for THIS provider, return the
    existing live-view URL so the frontend can re-open the tab.
    Otherwise reuse the user's existing Browserbase Context (shared
    across all marketplaces — cookies are domain-scoped within the
    Context) or create a new one, mint a fresh Live View session
    pre-navigated to the provider's login URL, persist the row as
    ``status="pending"``, and return the URL.
    """
    _check_provider(provider)
    user_id = str(user.id)

    # Reuse existing active link for this provider if present — no need
    # to re-provision a session.
    existing = await IntegrationAccountRow.get(session, user_id, provider)
    if (
        existing
        and existing.status == "active"
        and existing.browserbase_context_id
    ):
        return LinkInitResponse(
            authorize_url=existing.live_view_url or "",
            state=existing.browserbase_context_id,
            provider=provider,  # type: ignore[arg-type]
        )

    # Reuse ANY existing context for this user (one Context spans all
    # marketplaces — cookies are domain-scoped). Falls back to creating
    # a fresh context if the user has no rows yet.
    any_rows = await IntegrationAccountRow.list_for_user(session, user_id)
    context_id: str | None = None
    for row in any_rows:
        if row.browserbase_context_id:
            context_id = row.browserbase_context_id
            break
    if context_id is None:
        try:
            context_id = await bb_client.create_context()
        except BrowserbaseQuotaExhausted as exc:
            logger.warning(
                "link_integration: Browserbase quota exhausted (context create) "
                "provider=%s",
                provider,
            )
            raise HTTPException(
                status_code=402,
                detail=_QUOTA_DETAIL,
                headers={"X-Goti-Error-Code": "browserbase_quota_exhausted"},
            ) from exc
        except Exception as exc:  # noqa: BLE001 — surface as 502
            logger.exception(
                "link_integration: create_context failed for provider=%s",
                provider,
            )
            raise HTTPException(
                status_code=502,
                detail=f"failed to create Browserbase context: {exc!s}",
            ) from exc

    target_url = _MARKETPLACE_LOGIN_URLS[provider]
    try:
        session_id, live_view_url = await bb_client.create_session_with_live_view(
            context_id, target_url
        )
    except BrowserbaseQuotaExhausted as exc:
        logger.warning(
            "link_integration: Browserbase quota exhausted (session create) "
            "context=%s provider=%s",
            context_id,
            provider,
        )
        raise HTTPException(
            status_code=402,
            detail=_QUOTA_DETAIL,
            headers={"X-Goti-Error-Code": "browserbase_quota_exhausted"},
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface as 502
        logger.exception(
            "link_integration: create_session_with_live_view failed "
            "context=%s provider=%s",
            context_id,
            provider,
        )
        raise HTTPException(
            status_code=502,
            detail=f"failed to create Browserbase session: {exc!s}",
        ) from exc

    # End any previously-minted kept-alive session for this row before
    # storing the new one — otherwise re-clicking "Link" leaks sessions.
    if existing and existing.live_view_session_id:
        try:
            await bb_client.end_session(existing.live_view_session_id)
        except Exception:  # noqa: BLE001 — best effort
            logger.warning(
                "link_integration: failed to release stale session %s",
                existing.live_view_session_id,
            )

    await IntegrationAccountRow.upsert(
        session,
        user_id=user_id,
        provider=provider,
        browserbase_context_id=context_id,
        live_view_url=live_view_url,
        live_view_session_id=session_id,
        status="pending",
    )
    await session.commit()

    return LinkInitResponse(
        authorize_url=live_view_url,
        state=context_id,
        provider=provider,  # type: ignore[arg-type]
    )


@router.post("/{provider}/finish")
@_rate_limit("10/minute")
async def finish_link(
    request: Request,
    provider: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Stage 2 of the Browserbase Context link flow.

    Called after the user has signed into the specific marketplace
    inside the Live View tab. We:

    1. Release the kept-alive Live View session so it doesn't idle.
    2. Mint a short headless session bound to the same Context and
       navigate to a per-marketplace "logged-in only" URL to confirm
       the cookies actually carry — if the marketplace bounces us to a
       login page, the user's login didn't take.
    3. Flip the row to ``status="active"`` on success, leave it
       ``pending`` (returning ``validated=false``) on failure so the
       UI can prompt the user to re-open the login tab.
    """
    _check_provider(provider)
    user_id = str(user.id)
    row = await IntegrationAccountRow.get(session, user_id, provider)
    if not row or not row.browserbase_context_id:
        raise HTTPException(
            status_code=400,
            detail="no pending link found — call /link first.",
        )

    # 1. Release the kept-alive Live View session.
    if row.live_view_session_id:
        try:
            await bb_client.end_session(row.live_view_session_id)
        except Exception:  # noqa: BLE001 — best effort
            logger.warning(
                "finish_link: end_session failed sid=%s",
                row.live_view_session_id,
            )

    # 2. Validate login by navigating to a marketplace-specific
    # "logged-in only" probe URL in a headless session.
    validated = True
    try:
        validated = await bb_client.validate_login(
            row.browserbase_context_id, provider
        )
    except Exception:  # noqa: BLE001 — degrade to auto-pass (logged inside)
        logger.exception(
            "finish_link: validate_login raised provider=%s", provider
        )

    if not validated:
        # Keep the row pending so the user can re-open the same tab via
        # /api/integrations and try again. Don't clear live_view_url —
        # it's still useful to re-attach. The session is already gone
        # but the marketplace re-mints one on the next link click.
        row.live_view_session_id = None
        await session.commit()
        return {
            "ok": False,
            "validated": False,
            "error": (
                "Login didn't take — when the tab loaded the marketplace, "
                "it still showed the login page. Try Link again and make "
                "sure you complete the sign-in before clicking I'm done."
            ),
        }

    row.status = "active"
    row.linked_at = datetime.now(timezone.utc)
    row.live_view_session_id = None
    await session.commit()
    return {"ok": True, "validated": True}


@router.get("", response_model=list[IntegrationAccount])
async def list_integrations(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[IntegrationAccount]:
    """Return one row per supported provider with linked status.

    Linked status is derived from any row whose ``status="active"``.
    Pending rows surface their ``live_view_url`` so the frontend can
    re-open the login tab if the user accidentally closed it before
    clicking "I'm done".
    """
    rows = await IntegrationAccountRow.list_for_user(session, str(user.id))
    by_provider: dict[str, IntegrationAccountRow] = {
        row.provider: row for row in rows
    }
    out: list[IntegrationAccount] = []
    for provider in ("fb", "nextdoor", "offerup", "craigslist"):
        row = by_provider.get(provider)
        is_active = bool(row and row.status == "active")
        out.append(
            IntegrationAccount(
                provider=provider,  # type: ignore[arg-type]
                linked=is_active,
                linked_at=row.linked_at if (row and is_active) else None,
                # Expose live_view_url for pending rows so the user can
                # re-open the login tab without re-minting a session.
                live_view_url=(
                    row.live_view_url
                    if (row and row.status == "pending")
                    else None
                ),
            )
        )
    return out


@router.post("/{provider}/unlink")
async def unlink_integration(
    provider: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Drop the ``integration_accounts`` row for ``provider``.

    Only deletes the upstream Browserbase Context when no other row for
    the user still references it — the Context is shared across all
    marketplaces the user logged into.

    After this, the user can re-run ``POST /api/integrations/{provider}/link``
    to start fresh for that marketplace.
    """
    _check_provider(provider)
    user_id_str = str(user.id)
    row = await IntegrationAccountRow.get(session, user_id_str, provider)
    if not row:
        return {"ok": True, "rows_deleted": 0}
    context_id = row.browserbase_context_id
    pending_session_id = row.live_view_session_id
    await session.delete(row)
    await session.commit()
    # Release any kept-alive Live View session this row was tracking —
    # otherwise unlinking mid-flow leaks the session until Browserbase
    # times it out.
    if pending_session_id:
        try:
            await bb_client.end_session(pending_session_id)
        except Exception:  # noqa: BLE001 — best effort
            logger.warning(
                "unlink_integration: end_session failed sid=%s",
                pending_session_id,
            )
    # Only delete the upstream Context when no other provider row still
    # references it. The Context holds cookies for every marketplace the
    # user signed into; dropping it prematurely would log the user out of
    # the other marketplaces they didn't unlink.
    if context_id:
        remaining = await IntegrationAccountRow.list_for_user(
            session, user_id_str
        )
        if not any(r.browserbase_context_id == context_id for r in remaining):
            await bb_client.delete_context(context_id)
    return {"ok": True, "rows_deleted": 1}
