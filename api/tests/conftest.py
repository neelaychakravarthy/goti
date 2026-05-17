"""Pytest fixtures shared across api/tests.

External calls (browser-use AI agent over Browserbase) are stubbed
per-test via ``unittest.mock.patch``; authentication is stubbed via
the ``stub_verify_token`` fixture so tests can hit protected routes
without a live Google OAuth flow.

When ``POSTGRES_URI`` is unset / empty, default to an in-memory SQLite
for the test process so DB-touching tests can run without a Postgres
dependency. The default is applied BEFORE any ``api.*`` modules import
so the eagerly-constructed engine in ``api/db.py`` picks up the
override.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Make `api.*` importable when pytest is run from the api/ dir.
_API_DIR = Path(__file__).resolve().parent.parent  # .../api
_REPO_ROOT = _API_DIR.parent
for p in (str(_REPO_ROOT), str(_API_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


# Apply test-only DB / control-plane overrides BEFORE any ``api.*``
# module imports. The bridge tests need a SQLite DB so they can run
# without a live Postgres; setting the env here ensures
# ``create_async_engine`` (called at ``api.db`` import time) picks up
# the override. Already-set values are preserved so live-marker tests
# can still target a real DB by setting POSTGRES_URI externally.
os.environ.setdefault("POSTGRES_URI", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AF_CONTROL_PLANE_URL", "http://localhost:8000")
os.environ.setdefault("AF_AGENT_SERVER_URL", "http://localhost:8080")
# Tests stub verify_google_id_token outright; we set this to a synthetic
# audience so the (unstubbed) verify path doesn't 500 on
# ``GOOGLE_OAUTH_CLIENT_ID is not configured``.
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com")

# Register cross-dialect DDL adapters so the Postgres-typed columns
# (UUID, JSONB) render under SQLite. Applied at import time so any
# ``Base.metadata.create_all`` in a test fixture works.
from sqlalchemy.dialects.postgresql import (  # noqa: E402
    JSONB as _PG_JSONB,
    UUID as _PG_UUID,
)
from sqlalchemy.ext.compiler import compiles as _compiles  # noqa: E402


@_compiles(_PG_UUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "CHAR(36)"


@_compiles(_PG_JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "TEXT"


# Phase U of the followups round — switch the SQLite test engine to
# StaticPool so a single shared connection backs every session for the
# pytest run. Without this, SQLite in-memory creates a fresh empty DB
# per connection, and stray background tasks holding the old
# connection while a new connection opens leads to "no such table"
# errors mid-test. ``check_same_thread=False`` lets aiosqlite's
# worker thread use the shared connection.
#
# Many tests in this suite use ``asyncio.run(...)`` which spins up a
# fresh event loop per call. ``StaticPool`` keeps a single underlying
# DB connection across those loops; ``check_same_thread=False``
# allows aiosqlite to use that connection from whichever worker
# thread the loop picks. This is the SQLAlchemy-recommended fix.
if os.environ["POSTGRES_URI"].startswith("sqlite"):
    from sqlalchemy.ext.asyncio import (  # noqa: E402
        async_sessionmaker as _async_sessionmaker,
        create_async_engine as _create_async_engine,
    )
    from sqlalchemy.pool import StaticPool as _StaticPool  # noqa: E402

    from api import db as _api_db  # noqa: E402

    _shared_engine = _create_async_engine(
        os.environ["POSTGRES_URI"],
        poolclass=_StaticPool,
        connect_args={"check_same_thread": False, "isolation_level": None},
        echo=False,
        future=True,
    )

    # Set SQLite journal_mode=WAL so concurrent readers don't block on
    # the lifecycle's writes — fixes the "cannot commit transaction —
    # statements in progress" race between the test's HTTP polling
    # and the lifecycle's commits.
    from sqlalchemy import event as _sa_event  # noqa: E402

    @_sa_event.listens_for(_shared_engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    _api_db.engine = _shared_engine
    _api_db.AsyncSessionLocal = _async_sessionmaker(
        _shared_engine,
        class_=_api_db.AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# Disable the FastAPI lifespan during tests — it runs in TestClient's
# own event loop and tries to call ``_interrupt_stale_async_tasks``
# against the StaticPool-bound engine, which deadlocks on teardown.
# Tests that need lifespan behaviour can ``patch.object`` it back in
# explicitly.
import api.main as _api_main_pre  # noqa: E402

_api_main_pre._run_migrations = lambda: None  # type: ignore[assignment]
_orig_interrupt = _api_main_pre._interrupt_stale_async_tasks


async def _noop_interrupt() -> None:
    return None


_api_main_pre._interrupt_stale_async_tasks = _noop_interrupt  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Auth stub — patch ``verify_google_id_token`` so tests can hit protected
# routes with a synthetic ``Authorization: Bearer test-token`` header
# without a live Google OAuth flow.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cancel_stray_background_tasks():
    """Cancel any ``asyncio.create_task`` background coroutines that
    outlived the previous test.

    The hunt lifecycle (``run_hunt_lifecycle``) spawns long-running
    coroutines that touch the in-memory SQLite DB. If they're still
    iterating when the next test starts, their commits race the new
    test's commits and SQLite raises ``cannot commit transaction —
    SQL statements in progress``. Cancelling pending tasks between
    tests keeps the DB single-writer.

    Phase U of the followups round reinforced this fixture: also reset
    the in-process task registry between tests (matches the StaticPool
    SQLite fix above by clearing all per-test global state).
    """
    yield
    # Best-effort: cancel any tasks that have a coroutine name from
    # the orchestration package. Pytest-asyncio manages the loop, so
    # we operate against the current running loop if there is one.
    try:
        loop = asyncio.get_event_loop()
        for task in asyncio.all_tasks(loop=loop):
            coro = getattr(task, "get_coro", lambda: None)()
            name = getattr(coro, "__qualname__", "") or ""
            mod = ""
            try:
                fr = getattr(coro, "cr_frame", None)
                if fr is not None:
                    mod = (fr.f_globals or {}).get("__name__", "") or ""
            except Exception:  # noqa: BLE001
                mod = ""
            if (
                "orchestration" in name
                or "_run_hunt_lifecycle" in name
                or "run_post_close_analysis" in name
                or "_analyze_one_job" in name
                or "api.orchestration" in mod
                or "_record_activity_async" in name
                or "_persist_task_start_async" in name
                or "_persist_task_finish_async" in name
            ):
                task.cancel()
    except Exception:  # noqa: BLE001 — teardown best-effort
        pass

    # Clear the in-process hunt-listings cache so test 2 doesn't see
    # test 1's leaked entries.
    try:
        from api.orchestration import hunts as _orch_hunts
        _orch_hunts._HUNT_LISTINGS.clear()
    except Exception:  # noqa: BLE001
        pass

    # Clear the in-process task registry so a leaked task started in
    # test 1 doesn't show up in test 2's running-task list.
    # Phase U: also awaits reset_for_tests via a fresh loop where
    # possible. reset_for_tests is synchronous today so the await
    # equivalent is direct call; if it grows async behaviour later
    # we'll need run_until_complete.
    try:
        from api.orchestration import tasks as _orch_tasks
        _orch_tasks.reset_for_tests()
    except Exception:  # noqa: BLE001
        pass

    # Clear the in-process notifications subscriber list so an
    # SSE-stream test leaving a queue registered doesn't leak into
    # the next test's enqueue counts.
    try:
        from api import notifications as _notif
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_notif.reset_for_tests())
        else:
            try:
                loop.run_until_complete(_notif.reset_for_tests())
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def stub_verify_token(monkeypatch):
    """Replace ``api.auth.verify_google_id_token`` with a synthetic stub.

    Default claims: sub=``test-sub``, email=``test@example.com``,
    name=``Test``. Sufficient for ``User.upsert_from_google`` to mint a
    consistent ``users`` row across calls in the same test.
    """
    import api.auth as auth_mod

    async def _stub(token: str) -> dict:
        return {
            "sub": "test-sub",
            "email": "test@example.com",
            "name": "Test",
            "picture": "https://lh3.googleusercontent.com/test",
        }

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _stub)
    return _stub


@pytest.fixture
def authed_headers() -> dict[str, str]:
    """Authorization header that ``stub_verify_token`` accepts."""
    return {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# External-integration stubs.
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_discovery(monkeypatch):
    """Monkeypatch ``api.integrations.discovery.search`` with canned listings.

    Returns 3 fake fb listings + 3 fake nextdoor listings whose titles
    echo the query so assertions can verify routing. The new signature
    takes ``user_id`` + keyword-only ``session`` — the stub accepts both
    via ``**kwargs`` so callers don't have to know which transport
    Goti's using.
    """
    from api.contracts import Listing
    from api.integrations import discovery as discovery_module

    async def _fake_search(
        user_id: str = "",
        query: str = "",
        marketplaces: list[str] | None = None,
        max_per_source: int = 10,
        *,
        session=None,
        hunt_id: str | None = None,
    ) -> list[Listing]:
        marketplaces = marketplaces or []
        out: list[Listing] = []
        for mp in marketplaces:
            if mp not in {"fb", "nextdoor", "offerup", "craigslist"}:
                continue
            for i in range(min(3, max_per_source)):
                out.append(
                    Listing(
                        id=f"{mp}_stub_{i:04d}",
                        title=f"Stub listing {i} — re: {query}",
                        price=100.0 + i * 25,
                        marketplace=mp,
                        url=f"https://example.com/{mp}/{i}",
                        description="Stubbed by stub_discovery fixture.",
                    )
                )
        return out

    monkeypatch.setattr(discovery_module, "search", _fake_search)
    return _fake_search


@pytest.fixture
def stub_browserbase(monkeypatch):
    """Stub Browserbase SDK + browser-agent surface for offline tests.

    Patches every async surface on ``api.integrations.browserbase.client``
    plus the high-level ``api.integrations.browser_agent.actions`` and
    ``api.integrations.browser_agent.client.run_action``. Tests need
    none of the real SDKs (no browser-use, no Playwright, no Browserbase
    HTTP).
    """
    import itertools

    from api.contracts import MessageId
    from api.integrations.browser_agent import actions as agent_actions
    from api.integrations.browser_agent import client as agent_client
    from api.integrations.browserbase import client as bb_client

    counter = itertools.count(1)

    async def _stub_create_context() -> str:
        return "bb_ctx_test"

    async def _stub_create_session_with_live_view(
        context_id: str, target_url: str
    ) -> tuple[str, str]:
        return ("bb_sess_test", "https://browserbase.com/live/test")

    async def _stub_create_headless_session(context_id: str) -> tuple[str, str]:
        return (
            "bb_sess_headless_test",
            "wss://connect.browserbase.com/test",
        )

    async def _stub_end_session(session_id: str) -> None:
        return None

    async def _stub_delete_context(context_id: str) -> None:
        return None

    async def _stub_validate_login(
        context_id: str, provider: str, timeout_ms: int = 15000
    ) -> bool:
        # Tests don't have a real Browserbase to navigate against;
        # auto-pass so the link flow flips to ``active`` as before the
        # validation roundtrip was added.
        return True

    # ---- browser_agent.client.run_action — the low-level seam ----
    async def _stub_run_action(
        context_id: str, task: str, *, max_steps: int = 25, **kwargs
    ):
        # Tests that need a structured result should monkeypatch the
        # higher-level actions directly. The default no-op return keeps
        # any unexpected invocation safe (no None-vs-list confusion in
        # the parser).
        return []

    monkeypatch.setattr(agent_client, "run_action", _stub_run_action)

    # ---- browser_agent.actions — the high-level seams ----
    async def _stub_search_listings(
        context_id: str,
        query: str,
        marketplaces: list[str],
        max_per_source: int = 5,
        **kwargs,
    ):
        return []

    # ``search_one_listing`` is the streaming action the production
    # discovery loop calls. The stub returns 3 canned listings per
    # marketplace, then ``None`` to signal "exhausted" so the loop
    # advances to the next provider.
    _emitted_per_marketplace: dict[str, int] = {}

    async def _stub_search_one_listing(
        context_id: str,
        query: str,
        marketplace: str,
        exclude: list[dict] | None = None,
        **kwargs,
    ):
        from api.contracts import Listing

        idx = _emitted_per_marketplace.get(marketplace, 0)
        if idx >= 3:
            return None
        _emitted_per_marketplace[marketplace] = idx + 1
        return Listing(
            id=f"{marketplace}_stub_{idx:04d}",
            title=f"Stub listing {idx} — re: {query}",
            price=100.0 + idx * 25,
            marketplace=marketplace,
            url=f"https://example.com/{marketplace}/{idx}",
            description="Stubbed by stub_browserbase fixture.",
        )

    async def _stub_send_message(
        context_id: str,
        listing_url: str,
        listing_id: str,
        message_text: str,
        marketplace: str,
        **kwargs,
    ):
        return MessageId(f"stub-{marketplace}-msg-{next(counter):04d}")

    async def _stub_fetch_replies(
        context_id: str,
        listing_url: str,
        listing_id: str,
        marketplace: str,
        since_ts: float,
        **kwargs,
    ):
        return []

    monkeypatch.setattr(agent_actions, "search_listings", _stub_search_listings)
    monkeypatch.setattr(
        agent_actions, "search_one_listing", _stub_search_one_listing
    )
    monkeypatch.setattr(agent_actions, "send_message", _stub_send_message)
    monkeypatch.setattr(agent_actions, "fetch_replies", _stub_fetch_replies)

    # ---- Browserbase SDK seams ----
    monkeypatch.setattr(bb_client, "create_context", _stub_create_context)
    monkeypatch.setattr(
        bb_client,
        "create_session_with_live_view",
        _stub_create_session_with_live_view,
    )
    monkeypatch.setattr(
        bb_client, "create_headless_session", _stub_create_headless_session
    )
    monkeypatch.setattr(bb_client, "end_session", _stub_end_session)
    monkeypatch.setattr(bb_client, "delete_context", _stub_delete_context)
    monkeypatch.setattr(bb_client, "validate_login", _stub_validate_login)

    # Pretend the test user has all four marketplaces linked, so the
    # streaming discovery loop doesn't short-circuit on
    # ``no linked marketplaces``. Each fake row carries a stub
    # Browserbase context id; the streamed listings come from
    # ``_stub_search_one_listing`` above.
    from api.models import IntegrationAccountRow as _IntegrationAccountRow

    class _FakeRow:
        def __init__(self, provider: str) -> None:
            self.provider = provider
            self.browserbase_context_id = "bb_ctx_test"
            self.status = "active"

    async def _stub_list_active_for_user(_session, _user_id: str):
        return [_FakeRow(p) for p in ("fb", "nextdoor", "offerup", "craigslist")]

    monkeypatch.setattr(
        _IntegrationAccountRow,
        "list_active_for_user",
        classmethod(lambda cls, s, u: _stub_list_active_for_user(s, u)),
    )

    # Stub the per-job lifecycle so background ``asyncio.create_task``
    # spawns from ``POST /api/hunts/{id}/jobs`` don't leak past test
    # boundaries (the real lifecycle tries to call LLMs / Browserbase
    # which fail with connection errors after the test stubs are torn
    # down). Tests that need to drive the job lifecycle should
    # re-patch this with their own implementation.
    from api.orchestration import jobs as _orch_jobs

    async def _stub_run_job_lifecycle_safe(*, job_id, listing, valuation):
        return None

    monkeypatch.setattr(
        _orch_jobs, "run_job_lifecycle_safe", _stub_run_job_lifecycle_safe
    )

    # Stub the analyzer fan-out — its DB writes against the shared
    # StaticPool connection can deadlock TestClient teardown when the
    # task is still in flight at exit. Tests that need the analyzer
    # call ``run_post_close_analysis`` directly via ``asyncio.run``.
    from api.orchestration import analyzer as _orch_analyzer

    async def _stub_run_post_close_analysis(*, hunt_id, user_id):
        return {
            "ok": True,
            "hunt_id": hunt_id,
            "analyzed_count": 0,
            "skipped_count": 0,
            "errors": [],
        }

    # Patch in orchestration.jobs (where ``finalize_close`` imports
    # from) so the route's background spawn lands on the no-op.
    monkeypatch.setattr(
        _orch_analyzer,
        "run_post_close_analysis",
        _stub_run_post_close_analysis,
    )

    return _stub_create_context
