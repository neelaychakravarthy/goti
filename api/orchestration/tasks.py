"""In-memory registry of running background tasks.

Phase L of the ancient-brewing-brooks chat-first plan. Surfaces what
Goti is doing right now — discovery, drafting, classifying, checking
replies, finalizing a close, analyzing closed negotiations — to the
frontend's hunt chat (top-of-page running-tasks strip + inline status
events in the polymorphic chat timeline).

Design:

- Single in-process dict ``_RUNNING_TASKS`` keyed by ``task_id``.
- ``start_task(kind, hunt_id, job_id, label) -> task_id`` adds a row
  and emits a ``task_started`` notification.
- ``finish_task(task_id, status, summary)`` removes the row and emits
  ``task_completed`` (status="completed") or ``task_errored``.
- ``list_running_for_hunt(hunt_id)`` returns the current rows for a
  hunt (used by ``GET /api/hunts/{id}/running-tasks``).
- ``list_running_all()`` returns every row (used by the cross-hunt
  Inbox in a future iteration).

Phase O of the followups round added durable persistence: ``start_task``
also upserts a row into ``async_tasks`` so the user can see + resume
stopped work across a process restart. The in-memory registry stays
(fast lookup); the row is the durable record. Phase Q added activity
backfill via ``record_activity`` — writes a ``HuntActivityEvent`` row
AND publishes it onto the notifications queue so the chat-first UI
sees the event live via SSE.

v1 is single-process / in-memory for the registry itself. Multi-instance
deploys would need a Redis pub/sub or Postgres-backed registry table;
documented as a follow-up in the plan's "Out-of-scope" section.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Optional

from api import notifications as notif_queue

logger = logging.getLogger(__name__)


# task_id -> {kind, hunt_id, job_id, label, started_at}
_RUNNING_TASKS: dict[str, dict] = {}


def _new_task_id() -> str:
    return uuid.uuid4().hex


def start_task(
    *,
    kind: str,
    hunt_id: Optional[str],
    job_id: Optional[str] = None,
    label: str,
    user_id: Optional[str] = None,
    resume_payload: Optional[dict] = None,
) -> str:
    """Register a running task and emit ``task_started`` notification.

    Returns the new task_id. Idempotent against double-registration —
    the caller is responsible for not calling start twice for the same
    logical task.

    NOTE: DB persistence (Phase O ``async_tasks`` row + Phase Q
    ``HuntActivityEvent`` row) is NOT performed by this sync entrypoint
    to avoid background-task hangs against aiosqlite under
    ``asyncio.run`` test boundaries. Async call paths should use
    ``await start_task_db(...)`` instead so the writes are inline and
    guarantee durability.
    """
    task_id = _new_task_id()
    started_at = time.time()
    row = {
        "task_id": task_id,
        "kind": kind,
        "hunt_id": hunt_id,
        "job_id": job_id,
        "label": label,
        "started_at": started_at,
        "user_id": user_id,
        "resume_payload": dict(resume_payload) if resume_payload else None,
    }
    _RUNNING_TASKS[task_id] = row
    _emit_event(
        kind_tag="task_started",
        user_id=user_id,
        hunt_id=hunt_id,
        job_id=job_id,
        task_id=task_id,
        task_kind=kind,
        label=label,
    )
    return task_id


async def start_task_db(
    *,
    kind: str,
    hunt_id: Optional[str],
    job_id: Optional[str] = None,
    label: str,
    user_id: Optional[str] = None,
    resume_payload: Optional[dict] = None,
) -> str:
    """Async-aware variant of ``start_task`` that awaits DB persistence.

    Use from async code paths where the caller can wait for the DB
    writes to complete. Returns the new task_id. Combines in-memory
    registration (via ``start_task``) + persistent ``async_tasks`` row
    + a ``task_started`` activity row hydration write.
    """
    task_id = start_task(
        kind=kind,
        hunt_id=hunt_id,
        job_id=job_id,
        label=label,
        user_id=user_id,
        resume_payload=resume_payload,
    )
    await _start_task_db_async(
        task_id=task_id,
        kind=kind,
        hunt_id=hunt_id,
        job_id=job_id,
        label=label,
        user_id=user_id,
        resume_payload=resume_payload,
    )
    return task_id


def finish_task(
    task_id: str,
    *,
    status: str = "completed",
    summary: Optional[str] = None,
) -> None:
    """Remove a task from the registry + emit a finish notification.

    ``status`` is ``"completed"`` (default) or ``"errored"``. Silently
    no-ops when ``task_id`` isn't in the registry (so double-finish or
    finish-on-startup-cleanup never raises).

    NOTE: DB persistence is NOT performed inline. Async call paths
    should use ``await finish_task_db(...)`` to update the durable
    ``async_tasks`` row + write the closing activity event.
    """
    row = _RUNNING_TASKS.pop(task_id, None)
    if row is None:
        logger.debug("finish_task: unknown task_id=%s", task_id)
        return
    finished_at = time.time()
    duration_s = max(0.0, finished_at - float(row.get("started_at") or finished_at))
    kind_tag = "task_completed" if status != "errored" else "task_errored"
    _emit_event(
        kind_tag=kind_tag,
        user_id=row.get("user_id"),
        hunt_id=row.get("hunt_id"),
        job_id=row.get("job_id"),
        task_id=task_id,
        task_kind=row.get("kind"),
        label=row.get("label"),
        status=status,
        summary=summary,
        duration_s=duration_s,
    )


async def finish_task_db(
    task_id: str,
    *,
    status: str = "completed",
    summary: Optional[str] = None,
) -> None:
    """Async variant of ``finish_task`` — does sync registry update +
    awaits DB persistence inline.

    Reads the in-memory row BEFORE removing it so the DB write picks
    up hunt_id / job_id / user_id / label without an extra DB lookup.
    """
    row = _RUNNING_TASKS.get(task_id)
    hunt_id = row.get("hunt_id") if row else None
    job_id = row.get("job_id") if row else None
    user_id = row.get("user_id") if row else None
    label = str(row.get("label") or "") if row else None
    finish_task(task_id, status=status, summary=summary)
    await _finish_task_db_async(
        task_id=task_id,
        status=status,
        summary=summary,
        hunt_id=hunt_id,
        job_id=job_id,
        user_id=user_id,
        label=label,
    )


# ---------------------------------------------------------------------------
# Background-task scheduling helpers. ``_schedule_bg`` runs a coroutine
# on the current loop and tracks the resulting task so it can be
# awaited by orchestration code if needed. Tasks are auto-removed on
# completion. We also add a done_callback that swallows + logs
# exceptions so a failing DB write doesn't bubble up.


_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _schedule_bg(coro) -> Optional[asyncio.Task]:
    """Schedule ``coro`` on the running event loop. Returns the task
    handle or ``None`` if there's no running loop.

    Track tasks in ``_BACKGROUND_TASKS`` so they can be drained / awaited
    by callers that want to ensure DB durability before returning.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return None
    if not loop.is_running():
        return None
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        return None
    except Exception:  # noqa: BLE001
        logger.exception("_schedule_bg: dispatch failed")
        return None

    _BACKGROUND_TASKS.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(t)
        # Surface task-level exceptions to logs (not to stdout).
        try:
            exc = t.exception()
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            exc = None
        if exc is not None and not isinstance(exc, asyncio.CancelledError):
            logger.warning(
                "_schedule_bg: background task raised: %s",
                exc,
            )

    task.add_done_callback(_on_done)
    return task


async def drain_background_tasks(timeout: float = 5.0) -> None:
    """Await every still-running background task up to ``timeout`` seconds.

    Used by orchestration coroutines that want to make sure their DB
    durability writes complete before returning (e.g. the analyzer
    pipeline ensuring the chat conversation hydrates with the
    analyzer's final tile).
    """
    pending = [t for t in _BACKGROUND_TASKS if not t.done()]
    if not pending:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "drain_background_tasks: %d task(s) didn't complete within %.1fs",
            len(pending),
            timeout,
        )


def list_running_for_hunt(hunt_id: str) -> list[dict]:
    """Return live task rows for ``hunt_id``, sorted oldest-first."""
    if not hunt_id:
        return []
    rows = [r for r in _RUNNING_TASKS.values() if r.get("hunt_id") == hunt_id]
    rows.sort(key=lambda r: float(r.get("started_at") or 0.0))
    return [_serialize(r) for r in rows]


def list_running_all() -> list[dict]:
    """Return every live task row across all hunts."""
    rows = list(_RUNNING_TASKS.values())
    rows.sort(key=lambda r: float(r.get("started_at") or 0.0))
    return [_serialize(r) for r in rows]


def reset_for_tests() -> None:
    """Clear the registry — test-only helper.

    Phase U: also cancels any pending background DB-write tasks so they
    don't leak across the test boundary and race the next test's
    SQLite connection.
    """
    _RUNNING_TASKS.clear()
    # Best-effort cancel of any in-flight DB-write background tasks.
    for t in list(_BACKGROUND_TASKS):
        if not t.done():
            t.cancel()
    _BACKGROUND_TASKS.clear()


def _serialize(row: dict) -> dict:
    started_at = row.get("started_at")
    return {
        "task_id": row.get("task_id"),
        "kind": row.get("kind"),
        "hunt_id": row.get("hunt_id"),
        "job_id": row.get("job_id"),
        "label": row.get("label"),
        "started_at": _iso(started_at) if started_at else None,
        "elapsed_s": max(0.0, time.time() - float(started_at)) if started_at else 0.0,
    }


def _iso(epoch_seconds: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc).isoformat()


def _emit_event(
    *,
    kind_tag: str,
    user_id: Optional[str],
    hunt_id: Optional[str],
    job_id: Optional[str],
    task_id: str,
    task_kind: Any,
    label: Any,
    status: Optional[str] = None,
    summary: Optional[str] = None,
    duration_s: Optional[float] = None,
) -> None:
    """Best-effort notification enqueue. Failures are logged + swallowed."""
    payload = {
        "kind_tag": kind_tag,
        "task_id": task_id,
        "task_kind": task_kind,
        "label": label,
        "hunt_id": hunt_id,
        "job_id": job_id,
    }
    if status is not None:
        payload["status"] = status
    if summary is not None:
        payload["summary"] = summary
    if duration_s is not None:
        payload["duration_s"] = duration_s

    event = {
        "id": f"task-{task_id}-{kind_tag}",
        "user_id": user_id,
        "hunt_id": hunt_id,
        "job_id": job_id,
        "kind": "info",
        "title": _title_for_tag(kind_tag, label),
        "body": summary or "",
        "payload": payload,
        "target_href": f"/c/{hunt_id}" if hunt_id else "/",
        "approval_request_id": None,
        "status": "unread",
        "created_at": _iso(time.time()),
        "read_at": None,
        "resolved_at": None,
    }

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        try:
            asyncio.create_task(notif_queue.enqueue(event))
        except RuntimeError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("_emit_event: enqueue scheduling failed")


def _title_for_tag(kind_tag: str, label: Any) -> str:
    text = str(label or "")
    if kind_tag == "task_started":
        return f"Started: {text}" if text else "Task started"
    if kind_tag == "task_completed":
        return f"Finished: {text}" if text else "Task finished"
    if kind_tag == "task_errored":
        return f"Errored: {text}" if text else "Task errored"
    return text or kind_tag


# ---------------------------------------------------------------------------
# Phase Q + P — record_activity wraps DB write + SSE push for chat hydration.
# ---------------------------------------------------------------------------


def record_activity(
    *,
    hunt_id: str,
    phase: str,
    user_id: Optional[str] = None,
    job_id: Optional[str] = None,
    action_summary: Optional[str] = None,
    next_goal: Optional[str] = None,
    thinking: Optional[str] = None,
    url: Optional[str] = None,
    push_to_queue: bool = True,
) -> None:
    """Persist a ``HuntActivityEvent`` row and (optionally) push it to the
    notifications SSE queue.

    Phase Q: writes the activity row so historical hydration (the hunt
    chat's initial-fetch via ``GET /api/hunts/{id}/activity``) captures
    every life-cycle event — discovery, listings, analyzer progress,
    task starts/completes.

    Phase P: when ``push_to_queue=True``, also enqueues the same payload
    onto the in-memory ``notif_queue`` as a synthetic notification with
    ``kind="info"`` and ``payload.kind_tag="hunt_activity"``. The
    chat-first hunt page subscribes via ``useNotifications()`` and
    merges the live event into the conversation without a polling
    round-trip.

    Sync entrypoint — schedules a tracked background task. Async
    callers should prefer ``await record_activity_async(...)`` to
    guarantee the DB write completes before returning (critical to
    avoid asyncio.run end-of-loop hangs on aiosqlite).
    """
    if not hunt_id:
        return
    _schedule_bg(
        _record_activity_async(
            hunt_id=hunt_id,
            phase=phase,
            user_id=user_id,
            job_id=job_id,
            action_summary=action_summary,
            next_goal=next_goal,
            thinking=thinking,
            url=url,
            push_to_queue=push_to_queue,
        )
    )


async def record_activity_async(
    *,
    hunt_id: str,
    phase: str,
    user_id: Optional[str] = None,
    job_id: Optional[str] = None,
    action_summary: Optional[str] = None,
    next_goal: Optional[str] = None,
    thinking: Optional[str] = None,
    url: Optional[str] = None,
    push_to_queue: bool = True,
) -> None:
    """Async-aware variant of ``record_activity`` that awaits the DB write."""
    if not hunt_id:
        return
    await _record_activity_async(
        hunt_id=hunt_id,
        phase=phase,
        user_id=user_id,
        job_id=job_id,
        action_summary=action_summary,
        next_goal=next_goal,
        thinking=thinking,
        url=url,
        push_to_queue=push_to_queue,
    )


# Serializes activity-row DB writes so concurrent record_activity
# calls don't race "cannot commit transaction — statements in
# progress" on the shared SQLite connection during tests + dev. In
# Postgres prod this is harmless (the lock is uncontended unless
# heaps of analyzer/discovery events fire at once, in which case
# brief serial writes are still safer than races).
_ACTIVITY_WRITE_LOCK = asyncio.Lock()


async def _record_activity_async(
    *,
    hunt_id: str,
    phase: str,
    user_id: Optional[str],
    job_id: Optional[str],
    action_summary: Optional[str],
    next_goal: Optional[str],
    thinking: Optional[str],
    url: Optional[str],
    push_to_queue: bool,
) -> None:
    """Backend of ``record_activity`` — runs on the asyncio loop."""
    # 1) DB write — skip when the hunt FK can't be satisfied (the
    # activity row has a FK on hunts.id, so writing an orphan row
    # raises).
    activity_id: Optional[str] = None
    created_at_iso: Optional[str] = None
    async with _ACTIVITY_WRITE_LOCK:
        try:
            from api.db import AsyncSessionLocal
            from api.models import HuntActivityEvent as _HAE

            async with AsyncSessionLocal() as s:
                # step_idx is monotonic-ish per (hunt, phase). Best-effort:
                # use a UTC ms timestamp so concurrent writers don't collide
                # and the timeline ordering is deterministic.
                step_idx = int(time.time() * 1000) % 2_000_000_000
                row = await _HAE.insert(
                    s,
                    hunt_id=hunt_id,
                    phase=phase,
                    step_idx=step_idx,
                    thinking=thinking,
                    next_goal=next_goal,
                    action_summary=action_summary,
                    url=url,
                    job_id=job_id,
                )
                activity_id = row.id
                created_at_iso = (
                    row.created_at.isoformat() if row.created_at else None
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # FK-violation (hunt missing) is a common best-effort case;
            # log at debug to avoid noisy test output. Anything else
            # gets a warning.
            msg = str(exc).lower()
            if "foreign key" in msg or "no such" in msg:
                logger.debug(
                    "_record_activity_async: DB write skipped hunt=%s phase=%s: %s",
                    hunt_id,
                    phase,
                    exc,
                )
            else:
                logger.warning(
                    "_record_activity_async: DB write failed hunt=%s phase=%s: %s",
                    hunt_id,
                    phase,
                    exc,
                )

    if not push_to_queue or activity_id is None:
        return

    # 2) Push to notifications queue. Distinct ``kind_tag`` so the
    # frontend's chat consumer can identify this as a hunt-activity
    # event (rendered via the existing ActivityRow path). ``kind`` is
    # ``"info"`` so default consumers ignore it cleanly.
    title_source = action_summary or next_goal or phase or ""
    event = {
        "id": f"hunt-activity-{activity_id}",
        "user_id": user_id,
        "hunt_id": hunt_id,
        "job_id": job_id,
        "kind": "info",
        "title": title_source.strip() if isinstance(title_source, str) else phase,
        "body": next_goal or thinking or "",
        "payload": {
            "kind_tag": "hunt_activity",
            "activity_id": activity_id,
            "hunt_id": hunt_id,
            "job_id": job_id,
            "phase": phase,
            "thinking": thinking,
            "next_goal": next_goal,
            "action_summary": action_summary,
            "url": url,
            "step_idx": None,
            "created_at": created_at_iso,
        },
        "target_href": f"/c/{hunt_id}",
        "approval_request_id": None,
        "status": "unread",
        "created_at": created_at_iso,
        "read_at": None,
        "resolved_at": None,
    }
    try:
        await notif_queue.enqueue(event)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception(
            "_record_activity_async: enqueue failed hunt=%s phase=%s",
            hunt_id,
            phase,
        )


# ---------------------------------------------------------------------------
# Phase O — persistence: async_tasks row upserts.
# ---------------------------------------------------------------------------


async def _start_task_db_async(
    *,
    task_id: str,
    kind: str,
    hunt_id: Optional[str],
    job_id: Optional[str],
    label: str,
    user_id: Optional[str],
    resume_payload: Optional[dict],
) -> None:
    """Persist the ``async_tasks`` row + the ``task_started`` activity row.

    Tolerates missing async_tasks table (first boot before migration
    applies) by skipping the DB write. Tolerates missing hunt FK by
    skipping the activity write.
    """
    # Async-tasks row.
    try:
        from api.db import AsyncSessionLocal
        from api.models import AsyncTaskRow

        async with AsyncSessionLocal() as s:
            await AsyncTaskRow.upsert_start(
                s,
                task_id=task_id,
                kind=kind,
                hunt_id=hunt_id,
                job_id=job_id,
                label=label,
                user_id=user_id or "",
                resume_payload=resume_payload,
            )
            await s.commit()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception(
            "_start_task_db_async: async_tasks write failed task=%s",
            task_id,
        )

    # Activity row (phase=task_started) — only when hunt_id is set.
    if hunt_id:
        try:
            await _record_activity_async(
                hunt_id=hunt_id,
                phase="task_started",
                user_id=user_id,
                job_id=job_id,
                action_summary=label,
                next_goal=None,
                thinking=None,
                url=None,
                push_to_queue=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "_start_task_db_async: activity write failed task=%s",
                task_id,
            )


async def _finish_task_db_async(
    *,
    task_id: str,
    status: str,
    summary: Optional[str],
    hunt_id: Optional[str],
    job_id: Optional[str],
    user_id: Optional[str],
    label: Optional[str],
) -> None:
    """Mark the durable async_tasks row finished + emit the closing
    activity event."""
    try:
        from api.db import AsyncSessionLocal
        from api.models import AsyncTaskRow

        async with AsyncSessionLocal() as s:
            await AsyncTaskRow.mark_finished(
                s,
                task_id=task_id,
                status=status if status in ("completed", "errored") else "completed",
                summary=summary,
            )
            await s.commit()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception(
            "_finish_task_db_async: DB write failed task=%s", task_id
        )

    if hunt_id:
        try:
            phase = (
                "task_completed" if status != "errored" else "task_errored"
            )
            await _record_activity_async(
                hunt_id=hunt_id,
                phase=phase,
                user_id=user_id,
                job_id=job_id,
                action_summary=label or "",
                next_goal=summary,
                thinking=None,
                url=None,
                push_to_queue=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception(
                "_finish_task_db_async: activity write failed task=%s",
                task_id,
            )
