"""Goti FastAPI app entrypoint.

Mounts all routers and (on startup):
1. Runs Alembic migrations so a fresh ``docker compose up`` produces a
   working DB without any manual steps.
2. Finalizes any hunts left in a non-terminal status by the previous
   process (``_finalize_inflight_hunts``) — they're marked ``error``
   with an explanatory notification rather than auto-resumed. See the
   function docstring for the rationale.
3. Logs warnings for missing required env vars so deployers can
   diagnose missing config without trying every endpoint.

CORS: comma-separated origins via ``GOTI_ALLOWED_ORIGINS``. Empty
default falls back to ``localhost:3000`` + ``*.vercel.app`` (dev-
friendly).

Rate limiting: ``slowapi`` per-route. Default 100/min; expensive
endpoints (``POST /api/goals``, OAuth init, approval clicks) get
stricter limits — see the per-route decorators.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.rate_limit import limiter
from api.routes import (
    adapter,
    agent_bridge,
    approvals,
    goals,
    health,
    hunts,
    inbox,
    integrations,
    jobs,
    me,
    memory,
    notifications,
    tasks as tasks_routes,
)

logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Run Alembic `upgrade head` against the configured database.

    Imported lazily so the module is importable even without alembic in dev.
    """
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        logger.warning("alembic not installed; skipping migration step.")
        return

    cfg_path = Path(__file__).resolve().parent / "alembic.ini"
    if not cfg_path.exists():
        logger.warning("alembic.ini not found at %s; skipping migrations.", cfg_path)
        return

    cfg = Config(str(cfg_path))
    # Tell alembic where the migration scripts live (relative paths inside
    # alembic.ini are resolved relative to the ini, but we make it explicit
    # to be robust to CWD differences between local + docker).
    cfg.set_main_option("script_location", str(cfg_path.parent / "alembic"))

    # Pipe the resolved Postgres URL into alembic so env.py can pick it up.
    from api.config import get_settings

    db_url = get_settings().database_url
    cfg.set_main_option("sqlalchemy.url", db_url)
    os.environ.setdefault("ALEMBIC_DATABASE_URL", db_url)

    logger.info("Running alembic upgrade head against %s", db_url)
    try:
        command.upgrade(cfg, "head")
        logger.info("Alembic migrations applied.")
    except Exception:  # noqa: BLE001
        logger.exception("Alembic migration failed (continuing so the app still serves).")


def _log_env_warnings() -> None:
    """Log warnings on missing required env vars.

    Doesn't fail-fast — lets dev work with partial config. Surfaced so
    a deployer can diagnose "discovery returns 500" without spelunking.
    """
    from api.config import get_settings

    s = get_settings()
    if not s.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set — LLM-driven reasoners + browser-use will fail."
        )
    if not s.everos_api_key:
        logger.info(
            "EVEROS_API_KEY not set — Cases/Skills will be empty in the Playbook view."
        )
    if not s.google_oauth_client_id:
        logger.warning(
            "GOOGLE_OAUTH_CLIENT_ID not set — auth will reject all tokens."
        )


async def _finalize_inflight_hunts() -> None:
    """No-op on startup.

    Earlier versions of this hook tried to do something useful on
    restart — first auto-resume in-flight hunt lifecycles (which
    spawned duplicate Browserbase sessions per hunt on every boot)
    and later mark them as ``error`` (which clobbered hunts still
    actively running on a parallel uvicorn worker after a
    soft-reload).

    Both behaviours were worse than doing nothing. uvicorn --reload
    spawns a new worker before the old one drains, so background
    tasks from the previous worker keep running while the new
    worker's lifespan runs. Touching the DB from the new worker
    races the still-live tasks.

    Now we just leave stale hunts alone. They show in the sidebar
    until the user deletes them via the Delete-hunt button; no
    background tasks get spawned or killed automatically. The
    auto-resume code is gone; manual recovery is the right tradeoff
    for the dev / hackathon scale where soft-reload is constant.
    """
    return None


async def _interrupt_stale_async_tasks() -> None:
    """Flip every ``running`` async_tasks row to ``interrupted`` on boot.

    Phase O of the followups round. Captures post-crash state — when
    the process restarts, in-memory ``_RUNNING_TASKS`` is empty, but
    the durable rows still say ``running``. We flip them so the
    chat-first UI surfaces a "Stopped" strip with a Resume button
    per row.

    Best-effort: failures (e.g. table missing on first boot before
    migrations apply, or transient connection issues) are logged +
    swallowed so the app still serves.
    """
    try:
        from api.db import AsyncSessionLocal
        from api.models import AsyncTaskRow

        async with AsyncSessionLocal() as s:
            count = await AsyncTaskRow.mark_all_running_interrupted(s)
            await s.commit()
        if count:
            logger.info(
                "_interrupt_stale_async_tasks: flipped %d running row(s) to "
                "interrupted on startup",
                count,
            )
    except Exception as exc:  # noqa: BLE001
        # Common case during tests / first boot before alembic head
        # applies: the ``async_tasks`` table doesn't exist yet. Surface
        # at INFO level so startup logs aren't noisy.
        msg = str(exc).lower()
        if "no such table" in msg or "does not exist" in msg:
            logger.info(
                "_interrupt_stale_async_tasks: async_tasks table not "
                "present yet (first boot / fresh schema); skipping"
            )
        else:
            logger.warning(
                "_interrupt_stale_async_tasks: failed to flip running rows "
                "(continuing): %s",
                exc,
            )


# Legacy alias — kept so external callers (tests, etc.) that imported
# the old name still work. Routes to the no-op behaviour.
_resume_inflight_hunts = _finalize_inflight_hunts


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    # Log env-config warnings up front so deployers see them in startup logs.
    try:
        _log_env_warnings()
    except Exception:  # noqa: BLE001 — never block startup on a logging step
        logger.exception("_log_env_warnings raised — continuing.")
    # alembic's env.py calls asyncio.run() internally, which collides with
    # the running FastAPI event loop — push the whole migration step onto
    # a worker thread so it has its own fresh loop.
    await asyncio.to_thread(_run_migrations)
    # Best-effort resumption of in-flight hunt lifecycles. Runs AFTER
    # migrations so the schema is in shape before we touch the hunts
    # table. Failures are logged + swallowed inside the helper so a
    # bad recovery never blocks the app from serving.
    try:
        await _resume_inflight_hunts()
    except Exception:  # noqa: BLE001 — never crash startup
        logger.exception("Hunt resumption failed (continuing without resume).")
    # Phase O — flip any leftover ``running`` async_tasks rows to
    # ``interrupted`` so the UI surfaces them with a Resume button.
    # Must run BEFORE the app accepts requests so the in-memory task
    # registry (empty on boot) can't race with a user POSTing /resume.
    try:
        await _interrupt_stale_async_tasks()
    except Exception:  # noqa: BLE001 — never crash startup
        logger.exception(
            "Async task interruption-on-boot failed (continuing)."
        )
    yield


# ---------------------------------------------------------------------------
# CORS origin resolution. ``GOTI_ALLOWED_ORIGINS`` is a comma-separated
# list of explicit origins. Empty default falls back to dev-friendly
# origins (localhost + Vercel preview wildcard).
# ---------------------------------------------------------------------------


def _resolve_cors_origins() -> list[str]:
    raw = os.getenv("GOTI_ALLOWED_ORIGINS", "")
    if raw.strip():
        return [o.strip() for o in raw.split(",") if o.strip()]
    # Dev default — Vercel preview + localhost
    return [
        "http://localhost:3000",
        "https://*.vercel.app",  # Vercel previews
    ]


app = FastAPI(
    title="Goti API",
    description="Agentic negotiation backend.",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Approvals router mounted FIRST so its real ``POST /api/approvals/{id}``
# (with AgentField webhook bridging) wins over any adapter-shape route.
# ``goals`` mounts BEFORE ``adapter`` so the real hunt-lifecycle handlers
# at ``POST /api/goals`` + ``GET /api/goals/{hunt_id}/listings`` win over
# any adapter shape that might still claim those paths.
app.include_router(approvals.router)
app.include_router(goals.router)
app.include_router(hunts.router)
app.include_router(adapter.router)
app.include_router(jobs.router)
app.include_router(memory.router)
app.include_router(integrations.router)
app.include_router(notifications.router)
app.include_router(agent_bridge.router)
app.include_router(me.router)
app.include_router(inbox.router)
app.include_router(tasks_routes.router)
app.include_router(health.router)


@app.get("/")
async def root() -> dict:
    return {"service": "goti-api", "status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
