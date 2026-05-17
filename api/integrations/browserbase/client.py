"""Browserbase Python SDK wrapper.

Goti owns one ``BROWSERBASE_API_KEY`` + ``BROWSERBASE_PROJECT_ID``. Each
Goti user gets one Context (``bb_ctx_*``) that persists their
FB Marketplace + Nextdoor cookies across sessions.

For login: we create a session bound to the context + return the live
view URL so the user can open Chrome remotely, navigate to FB / Nextdoor,
log in, and close the tab. Cookies persist in the Context because the
session sets ``persist: True``.

For send / fetch: we create a fresh session with ``persist: True`` so
any new cookies the marketplace drops are saved back to the context.

The ``browserbase`` SDK is sync (built on httpx + Pydantic); we wrap
each call in ``asyncio.to_thread`` so callers in the FastAPI request
path don't block the event loop. Method signatures here verified
against ``browserbase==1.10.0`` (see
``api/.venv/lib/python3.11/site-packages/browserbase/resources/``).
"""

from __future__ import annotations

import asyncio
import logging

from api.config import get_settings

logger = logging.getLogger(__name__)


# Global concurrent-session semaphore.
#
# Lives at the LOWEST level so every code path that ever mints a
# Browserbase session goes through it — link flow's Live View, the
# /finish validation probe, browser-use Agent runs, and any future
# caller. Without this gating, the link flow and validate_login
# bypass the semaphore and we end up with N+ concurrent sessions
# even though we think we're capped at N.
#
# Permits = ``settings.browserbase_max_concurrent`` (default 24,
# matching Browserbase Developer tier with one slot reserved). Lazily
# constructed because asyncio.Semaphore must be created inside a
# running event loop.
_session_semaphore: asyncio.Semaphore | None = None


def _get_session_semaphore() -> asyncio.Semaphore:
    global _session_semaphore
    if _session_semaphore is None:
        settings = get_settings()
        cap = max(1, int(settings.browserbase_max_concurrent or 1))
        _session_semaphore = asyncio.Semaphore(cap)
    return _session_semaphore


# Counter of currently-active sessions Goti has minted (incremented on
# create, decremented on end_session). Exposed via logging so we can
# see in the logs when concurrent counts drift unexpectedly high.
_active_session_count: int = 0


def _log_active(delta: int, kind: str, session_id: str) -> None:
    global _active_session_count
    _active_session_count = max(0, _active_session_count + delta)
    logger.info(
        "browserbase: %s %s session=%s active_count=%d",
        "created" if delta > 0 else "ended",
        kind,
        session_id,
        _active_session_count,
    )


class BrowserbaseError(RuntimeError):
    """Raised when Browserbase config is missing or an SDK call fails."""


class BrowserbaseQuotaExhausted(BrowserbaseError):
    """Raised when Browserbase returns 402 Payment Required.

    Free-tier accounts get a monthly browser-minutes allowance (60 min
    on free). When it's exhausted, every ``sessions.create`` call from
    Browserbase returns 402 with ``message: "Free plan browser minutes
    limit reached"``. This subclass lets callers surface a dedicated
    UI state (upgrade banner with a link to browserbase.com/plans)
    instead of a generic 502.
    """


def _is_quota_exhausted(exc: Exception) -> bool:
    """True if ``exc`` is a Browserbase 402 (monthly minutes cap hit)."""
    status = getattr(exc, "status_code", None)
    if status == 402:
        return True
    # Some SDK paths wrap the response without setting status_code on the
    # exception class — fall back to string match on the well-known
    # error body.
    return "Free plan browser minutes limit" in str(exc)


def _client():
    """Lazy import + construct the Browserbase SDK client.

    Raises ``BrowserbaseError`` when either the API key or project id is
    unset — callers should surface this as a 502 / log a warning rather
    than 500.
    """
    settings = get_settings()
    if not settings.browserbase_api_key:
        raise BrowserbaseError("BROWSERBASE_API_KEY not configured")
    if not settings.browserbase_project_id:
        raise BrowserbaseError("BROWSERBASE_PROJECT_ID not configured")
    from browserbase import Browserbase

    return Browserbase(api_key=settings.browserbase_api_key)


async def create_context() -> str:
    """Provision a new Context. Returns the ``bb_ctx_*`` id."""
    settings = get_settings()

    def _do() -> str:
        bb = _client()
        # ContextsResource.create signature (browserbase 1.10):
        #   create(*, project_id: str) -> ContextCreateResponse
        ctx = bb.contexts.create(project_id=settings.browserbase_project_id)
        return ctx.id

    try:
        return await asyncio.to_thread(_do)
    except Exception as exc:  # noqa: BLE001 — translate quota errors
        if _is_quota_exhausted(exc):
            raise BrowserbaseQuotaExhausted(str(exc)) from exc
        raise


async def delete_context(context_id: str) -> None:
    """Best-effort delete; swallows errors so a stale row can still be
    removed locally."""

    def _do() -> None:
        try:
            bb = _client()
            bb.contexts.delete(context_id)
        except Exception as exc:  # noqa: BLE001 — delete is best-effort
            logger.warning("delete_context %s failed: %s", context_id, exc)

    await asyncio.to_thread(_do)


# Per-marketplace login URLs. Each tile in Goti's UI opens a Browserbase
# session pre-navigated to ONE of these URLs so the user lands directly
# on the right login surface — no in-browser landing page that strands
# them after the first login.
_MARKETPLACE_LOGIN_URLS: dict[str, str] = {
    "fb": "https://www.facebook.com/marketplace",
    "nextdoor": "https://nextdoor.com/login/",
    "offerup": "https://offerup.com/login",
    "craigslist": "https://accounts.craigslist.org/login",
}


async def _pre_navigate_session(connect_url: str, target_url: str) -> None:
    """Attach to the session via CDP + navigate to ``target_url``.

    Disconnects cleanly so the session stays alive for the user. Errors
    are logged but not raised — a session that opens at ``about:blank``
    is degraded UX, not broken; the user can still type a URL manually.
    """
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(connect_url)
            try:
                # Use the existing context (Browserbase pre-loads it with
                # the persisted cookies); reuse the existing tab if one
                # exists, else open a new one.
                contexts = browser.contexts
                ctx = contexts[0] if contexts else await browser.new_context()
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            finally:
                # ``browser.close()`` on a CDP-connected browser just
                # disconnects our client — the session keeps running.
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — degraded UX, not broken
        logger.warning(
            "_pre_navigate_session: failed to pre-load %s: %s",
            target_url,
            exc,
        )


async def create_session_with_live_view(
    context_id: str, target_url: str
) -> tuple[str, str]:
    """Create a Session bound to ``context_id`` + return
    ``(session_id, live_view_url)``.

    The session is pre-navigated to ``target_url`` (typically a specific
    marketplace's login page from ``_MARKETPLACE_LOGIN_URLS``) so the user
    lands directly on the login surface they want. ``keep_alive=True`` so
    the session doesn't close while the user is logging in (the caller
    should ``end_session`` once the user reports they're done). The
    returned ``live_view_url`` is the fullscreen debugger URL the user
    opens in their own browser.
    """
    settings = get_settings()

    def _do_create() -> tuple[str, str, str]:
        bb = _client()
        session = bb.sessions.create(
            project_id=settings.browserbase_project_id,
            browser_settings={
                "context": {"id": context_id, "persist": True},
            },
            keep_alive=True,
        )
        debug = bb.sessions.debug(session.id)
        live_url = getattr(debug, "debugger_fullscreen_url", None) or getattr(
            debug, "debugger_url", None
        )
        if not live_url:
            raise BrowserbaseError(
                f"No live view URL in debug response: {debug!r}"
            )
        return session.id, live_url, session.connect_url

    # Gate against the project-wide concurrent-session quota. Live
    # View sessions count against the same upstream cap as headless
    # ones — without the semaphore, the link flow could mint sessions
    # that push a parallel browser-use Agent run over the limit.
    await _get_session_semaphore().acquire()
    try:
        session_id, live_url, connect_url = await asyncio.to_thread(_do_create)
    except Exception as exc:  # noqa: BLE001 — translate quota errors
        _get_session_semaphore().release()
        if _is_quota_exhausted(exc):
            raise BrowserbaseQuotaExhausted(str(exc)) from exc
        raise
    _log_active(+1, "live-view", session_id)

    # Best-effort pre-navigation. Adds ~2-4s to the link flow but means
    # the user lands on the chosen marketplace login instead of about:blank.
    await _pre_navigate_session(connect_url, target_url)

    return session_id, live_url


async def end_session(session_id: str) -> None:
    """Request the release of a kept-alive session.

    Called after the user finishes their interactive login flow. The
    underlying SDK ``sessions.update`` accepts only
    ``status="REQUEST_RELEASE"`` — anything else 4xxs.

    Releases the semaphore permit acquired at session create time so a
    crashed upstream call doesn't leak the slot indefinitely.
    """
    settings = get_settings()

    def _do() -> None:
        try:
            bb = _client()
            bb.sessions.update(
                session_id,
                status="REQUEST_RELEASE",
                project_id=settings.browserbase_project_id,
            )
        except Exception as exc:  # noqa: BLE001 — end_session is best-effort
            logger.warning("end_session %s failed: %s", session_id, exc)

    try:
        await asyncio.to_thread(_do)
    finally:
        _log_active(-1, "session", session_id)
        try:
            _get_session_semaphore().release()
        except ValueError:
            # Already released (e.g. paired end_session called twice
            # from overlapping cleanup paths). Swallow — releasing
            # twice is logically a no-op for our quota accounting.
            logger.debug("end_session: semaphore already at full capacity")


async def create_headless_session(context_id: str) -> tuple[str, str]:
    """Create a non-live session for backend automation.

    Returns ``(session_id, connect_url)`` — caller passes ``connect_url``
    to Playwright's ``chromium.connect_over_cdp`` to drive the browser
    headlessly. The session is short-lived (no ``keep_alive``) so it
    auto-closes when the Playwright connection drops; callers can also
    call ``end_session`` explicitly to force closure.
    """
    settings = get_settings()

    def _do() -> tuple[str, str]:
        bb = _client()
        session = bb.sessions.create(
            project_id=settings.browserbase_project_id,
            browser_settings={
                "context": {"id": context_id, "persist": True},
            },
        )
        return session.id, session.connect_url

    # Gate against the project-wide concurrent-session quota.
    await _get_session_semaphore().acquire()
    try:
        session_id, connect_url = await asyncio.to_thread(_do)
    except Exception as exc:  # noqa: BLE001 — translate quota errors
        _get_session_semaphore().release()
        if _is_quota_exhausted(exc):
            raise BrowserbaseQuotaExhausted(str(exc)) from exc
        raise
    _log_active(+1, "headless", session_id)
    return session_id, connect_url


# Per-marketplace URLs whose redirect-to-login behaviour acts as a quick
# login check. The validator navigates here in a headless session bound
# to the user's Context; if the page ends up at a ``/login`` (or
# similar) URL, the user is not signed in. ``None`` means the
# marketplace doesn't require login at all — validation auto-passes.
_VALIDATION_PROBES: dict[str, str | None] = {
    "fb": "https://www.facebook.com/marketplace/you/selling",
    "nextdoor": "https://nextdoor.com/news_feed/",
    "offerup": "https://offerup.com/messages/",
    # Craigslist's "logged-in" surface is the email-only post flow;
    # discovery + negotiate flows work without an account, so we skip
    # validation entirely for it.
    "craigslist": None,
}

# Substrings that, when found in the final URL after navigation, signal
# the marketplace bounced us to a login page.
_LOGGED_OUT_URL_MARKERS = (
    "/login",
    "/signin",
    "/sign_in",
    "/auth/",
    "login.php",
)


async def validate_login(
    context_id: str, provider: str, timeout_ms: int = 15000
) -> bool:
    """Best-effort check that the user is actually signed into ``provider``.

    Mints a short-lived headless session bound to ``context_id``,
    navigates to a per-marketplace "logged-in only" URL via Playwright
    over CDP, and inspects the final URL. If the marketplace bounced us
    to a login page, returns ``False``; otherwise ``True``.

    Returns ``True`` (auto-pass) when the provider has no validation
    probe (e.g. ``craigslist``) and when validation can't run due to
    transport / Playwright failures — the user's "I'm done" click is
    treated as the authoritative signal in those cases.
    """
    probe_url = _VALIDATION_PROBES.get(provider)
    if probe_url is None:
        return True

    try:
        session_id, connect_url = await create_headless_session(context_id)
    except Exception as exc:  # noqa: BLE001 — degrade to auto-pass
        logger.warning(
            "validate_login: failed to mint headless session provider=%s: %s",
            provider,
            exc,
        )
        return True

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(connect_url)
            try:
                ctx = (
                    browser.contexts[0]
                    if browser.contexts
                    else await browser.new_context()
                )
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                try:
                    await page.goto(
                        probe_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                except Exception:  # noqa: BLE001 — network blips → auto-pass
                    logger.warning(
                        "validate_login: navigation to %s failed", probe_url
                    )
                    return True
                final_url = (page.url or "").lower()
                logged_out = any(
                    marker in final_url for marker in _LOGGED_OUT_URL_MARKERS
                )
                return not logged_out
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — degrade to auto-pass
        logger.warning(
            "validate_login: Playwright check failed provider=%s: %s",
            provider,
            exc,
        )
        return True
    finally:
        await end_session(session_id)
