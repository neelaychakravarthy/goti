"""Server-Sent Events stream for ``GET /api/jobs/{job_id}/stream``.

DB-polling based: re-reads the job + messages + pending approval card every
``POLL_INTERVAL`` seconds, yields ``event: state`` on diffs, ``event: ping``
on idle gaps (so proxies don't close the connection), and exits naturally
on client disconnect.

Per the plan: a fresh DB session is opened inside the generator (the
dependency-injected request session would close as soon as the route
handler returns).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from sqlalchemy.exc import OperationalError

from api.db import AsyncSessionLocal
from api.orchestration.jobs import build_job_response

logger = logging.getLogger(__name__)

POLL_INTERVAL = 0.5
HEARTBEAT_INTERVAL = 30.0


def _serialize_snapshot(job_response) -> dict:
    """Reduce a JobContract to a JSON-serializable dict for SSE payloads."""
    if job_response is None:
        return {"missing": True}
    # Pydantic v2 — uses .model_dump(mode="json") for ISO-formatted datetimes.
    return job_response.model_dump(mode="json")


async def job_event_stream(job_id: str) -> AsyncGenerator[str, None]:
    """Yield SSE events for ``job_id``.

    Loops on POLL_INTERVAL; emits a ``state`` event when the serialized
    snapshot changes; emits a ``ping`` event when HEARTBEAT_INTERVAL has
    passed without a state diff. Exits when the client cancels (asyncio
    raises CancelledError into the generator).
    """
    last_snapshot: dict | None = None
    last_yield = time.time()

    # First emit: send the current state immediately so the client can
    # render without waiting for a diff or a heartbeat.
    try:
        async with AsyncSessionLocal() as session:
            job_response = await build_job_response(session, job_id)
            current = _serialize_snapshot(job_response)
        yield f"event: state\ndata: {json.dumps(current)}\n\n"
        last_snapshot = current
        last_yield = time.time()
    except Exception:  # noqa: BLE001 — graceful initial-yield failure
        logger.exception("job_event_stream: initial snapshot failed for job=%s", job_id)

    while True:
        try:
            async with AsyncSessionLocal() as session:
                try:
                    job_response = await build_job_response(session, job_id)
                except OperationalError:
                    logger.warning("job_event_stream: transient DB error; will retry")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
            current = _serialize_snapshot(job_response)
            if current != last_snapshot:
                yield f"event: state\ndata: {json.dumps(current)}\n\n"
                last_snapshot = current
                last_yield = time.time()
            elif time.time() - last_yield >= HEARTBEAT_INTERVAL:
                yield "event: ping\ndata: {}\n\n"
                last_yield = time.time()
            await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("job_event_stream: client disconnected job=%s", job_id)
            raise
        except Exception:  # noqa: BLE001 — keep the stream alive on unexpected errors
            logger.exception("job_event_stream: loop iteration failed for job=%s", job_id)
            await asyncio.sleep(POLL_INTERVAL)
