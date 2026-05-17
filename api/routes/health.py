"""Health probes — used by deploy platforms + monitoring.

Two endpoints:

- ``GET /api/healthz`` — liveness + dependency-shape probe. Returns
  ``{status, checks}`` describing the DB connection + external API key
  presence. No auth required (this is a liveness probe).
- ``GET /api/readyz`` — same as ``/api/healthz`` but maps the boolean
  bag into a ``ready`` flag for orchestrators that prefer the readiness
  shape.

``status`` resolves to ``"healthy"`` when DB is reachable AND every
required key is present (Anthropic + Google OAuth). EverOS +
Browserbase are treated as graceful-degrade dependencies — if their
keys are missing we return ``"degraded"`` but still 200, because the
core hunt-lifecycle paths work without them (discovery + negotiation
require Browserbase + Anthropic via the browser-agent).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from api.config import get_settings
from api.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


async def _check_db() -> str:
    """Try a SELECT 1 against the configured database."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 — probe never raises
        logger.warning("healthz: DB probe failed: %s", exc)
        return f"unreachable: {exc!s}"


def _build_checks() -> dict[str, Any]:
    """External API-key presence + Browserbase config status."""
    settings = get_settings()
    return {
        "anthropic_key": "ok" if settings.anthropic_api_key else "missing",
        "google_oauth": "ok" if settings.google_oauth_client_id else "missing",
        "everos_key": "ok" if settings.everos_api_key else "missing (graceful)",
        "browserbase_key": (
            "ok"
            if settings.browserbase_api_key
            else "missing (sends/replies will fail)"
        ),
        "browserbase_project_id": (
            "ok"
            if settings.browserbase_project_id
            else "missing (sends/replies will fail)"
        ),
    }


def _resolve_status(checks: dict[str, Any]) -> str:
    """Compute the overall health string from the per-check bag."""
    # Required dependencies — if these are missing, we're degraded.
    required = ("db", "anthropic_key", "google_oauth")
    for key in required:
        v = checks.get(key)
        if v != "ok":
            return "degraded"
    return "healthy"


@router.get("/api/healthz")
async def healthz() -> dict[str, Any]:
    """Liveness + dependency-shape probe.

    Returns ``{status, checks}``. No auth required.
    """
    checks: dict[str, Any] = {"db": await _check_db()}
    checks.update(_build_checks())
    return {"status": _resolve_status(checks), "checks": checks}


@router.get("/api/readyz")
async def readyz() -> dict[str, Any]:
    """Readiness probe — same checks as ``/api/healthz`` but with a
    ``ready: bool`` field for orchestrators that consume that shape."""
    payload = await healthz()
    return {**payload, "ready": payload["status"] == "healthy"}
