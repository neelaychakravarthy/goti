"""Goti FastAPI app entrypoint.

Mounts all five routers and (on startup) runs Alembic migrations so a fresh
`docker compose up` produces a working DB without any manual steps.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import approvals, goals, integrations, jobs, memory

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

    # Pipe the runtime DATABASE_URL into alembic so env.py can pick it up.
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


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    # alembic's env.py calls asyncio.run() internally, which collides with
    # the running FastAPI event loop — push the whole migration step onto
    # a worker thread so it has its own fresh loop.
    await asyncio.to_thread(_run_migrations)
    yield


app = FastAPI(
    title="Goti API",
    description="Agentic negotiation backend (Stream B).",
    version="0.1.0",
    lifespan=lifespan,
)

# Permissive CORS for local dev; tighten in deploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(goals.router)
app.include_router(jobs.router)
app.include_router(approvals.router)
app.include_router(memory.router)
app.include_router(integrations.router)


@app.get("/")
async def root() -> dict:
    return {"service": "goti-api", "status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
