"""Post-close analyzer orchestration.

Phase G' of the ancient-brewing-brooks chat-first plan. After a hunt's
``finalize_close`` completes (winner + sibling declines all closed),
this module fans out N PARALLEL ``analyze_negotiation`` reasoner
invocations — one per closed job — and writes each structured analysis
to EverOS as a single ``assistant``-role agent message whose ``content``
field carries ``json.dumps(analysis)``.

The flow:

1. Enumerate the hunt's closed jobs.
2. For each job: gather transcript + listing + outcome label, then
   ``asyncio.gather(*tasks)`` so all analyses run concurrently.
3. Each task calls ``invoke_reasoner("analyze_negotiation", ...)`` and
   on success writes the JSON-encoded analysis to EverOS via
   ``client.v1.memories.agent.add`` then ``flush`` for Skill extraction.

All failures are logged + swallowed — the analyzer is best-effort and
should never crash the close path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from sqlalchemy import select

from api.config import get_settings
from api.db import AsyncSessionLocal
from api.models import Hunt, Job as JobORM, ListingCache, MessageThread
from api.orchestration import tasks as task_registry
from api.orchestration.agents_client import invoke_reasoner

logger = logging.getLogger(__name__)


# Statuses considered "closed" for analyzer purposes — winner + siblings
# both land in ``closed`` post-finalize-close.
_CLOSED_STATUSES = ("closed",)


async def run_post_close_analysis(hunt_id: str, user_id: str) -> dict:
    """Fan out analyzer reasoner calls across every closed job in the hunt.

    Returns ``{ok, hunt_id, analyzed_count, skipped_count, errors}`` for
    debug/logging. The analyses themselves land in EverOS as one Case
    per job, indexed by ``session_id=goti-analysis-{job_id}``.

    Best-effort throughout — a missing EVEROS_API_KEY just logs + skips
    the write. Each analyzer invocation is independent so one failure
    doesn't bring down the others.
    """
    if not hunt_id or not user_id:
        return {
            "ok": False,
            "hunt_id": hunt_id,
            "analyzed_count": 0,
            "skipped_count": 0,
            "errors": ["missing hunt_id or user_id"],
        }

    parent_task_id: Optional[str] = None
    try:
        parent_task_id = await task_registry.start_task_db(
            kind="analyzer",
            hunt_id=hunt_id,
            label="Analyzing closed negotiations",
            user_id=user_id,
        )
    except Exception:  # noqa: BLE001 — registry never blocks the analyzer
        logger.exception(
            "run_post_close_analysis: failed to register parent task hunt=%s",
            hunt_id,
        )
        parent_task_id = None

    # Phase Q — emit an ``analyzer_started`` activity row so the chat-first
    # hunt page sees the analyzer kick off (live via SSE + on reload).
    try:
        await task_registry.record_activity_async(
            hunt_id=hunt_id,
            phase="analyzer_started",
            user_id=user_id,
            action_summary="Analyzing closed negotiations",
            next_goal=None,
            push_to_queue=True,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "run_post_close_analysis: analyzer_started activity emit failed hunt=%s",
            hunt_id,
        )

    try:
        async with AsyncSessionLocal() as session:
            hunt = await Hunt.get(session, hunt_id)
            if hunt is None:
                logger.info(
                    "run_post_close_analysis: hunt=%s not found; skipping",
                    hunt_id,
                )
                if parent_task_id:
                    await task_registry.finish_task_db(
                        parent_task_id, status="errored", summary="hunt not found"
                    )
                return {
                    "ok": False,
                    "hunt_id": hunt_id,
                    "analyzed_count": 0,
                    "skipped_count": 0,
                    "errors": ["hunt not found"],
                }
            hunt_goal = hunt.goal_text or ""

            closed_jobs_result = await session.execute(
                select(JobORM).where(
                    JobORM.hunt_id == hunt_id,
                    JobORM.status.in_(_CLOSED_STATUSES),
                )
            )
            closed_jobs = list(closed_jobs_result.scalars().all())

        if not closed_jobs:
            logger.info(
                "run_post_close_analysis: hunt=%s has no closed jobs",
                hunt_id,
            )
            if parent_task_id:
                await task_registry.finish_task_db(
                    parent_task_id,
                    status="completed",
                    summary="no closed jobs to analyze",
                )
            return {
                "ok": True,
                "hunt_id": hunt_id,
                "analyzed_count": 0,
                "skipped_count": 0,
                "errors": [],
            }

        # Spawn one task per closed job; let them run concurrently.
        analyzer_tasks = [
            _analyze_one_job(
                hunt_id=hunt_id,
                user_id=user_id,
                hunt_goal=hunt_goal,
                job=job,
            )
            for job in closed_jobs
        ]
        results = await asyncio.gather(*analyzer_tasks, return_exceptions=True)

        analyzed_count = 0
        skipped_count = 0
        errors: list[str] = []
        for job, outcome in zip(closed_jobs, results):
            if isinstance(outcome, Exception):
                errors.append(f"{job.id}: {outcome!s}")
                skipped_count += 1
                continue
            if isinstance(outcome, dict) and outcome.get("ok"):
                analyzed_count += 1
            else:
                skipped_count += 1
                if isinstance(outcome, dict) and outcome.get("error"):
                    errors.append(f"{job.id}: {outcome['error']}")

        logger.info(
            "run_post_close_analysis: hunt=%s analyzed=%d skipped=%d errors=%d",
            hunt_id,
            analyzed_count,
            skipped_count,
            len(errors),
        )
        if parent_task_id:
            await task_registry.finish_task_db(
                parent_task_id,
                status="completed" if not errors else "errored",
                summary=(
                    f"Analyzed {analyzed_count}/{len(closed_jobs)} closed "
                    f"negotiation(s)"
                ),
            )
        # Phase Q — emit ``analyzer_complete`` so the chat sees the
        # final summary inline (the task_completed event covers the
        # registry chip; this carries the body text).
        try:
            await task_registry.record_activity_async(
                hunt_id=hunt_id,
                phase="analyzer_complete",
                user_id=user_id,
                action_summary=(
                    f"Analyzed {analyzed_count}/{len(closed_jobs)} closed "
                    f"negotiation(s)"
                ),
                next_goal=None,
                push_to_queue=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "run_post_close_analysis: analyzer_complete activity emit failed hunt=%s",
                hunt_id,
            )
        return {
            "ok": True,
            "hunt_id": hunt_id,
            "analyzed_count": analyzed_count,
            "skipped_count": skipped_count,
            "errors": errors,
        }
    except Exception as exc:  # noqa: BLE001 — top-level catch
        logger.exception(
            "run_post_close_analysis: top-level error hunt=%s", hunt_id
        )
        if parent_task_id:
            try:
                await task_registry.finish_task_db(
                    parent_task_id, status="errored", summary=str(exc)
                )
            except Exception:  # noqa: BLE001
                task_registry.finish_task(
                    parent_task_id, status="errored", summary=str(exc)
                )
        return {
            "ok": False,
            "hunt_id": hunt_id,
            "analyzed_count": 0,
            "skipped_count": 0,
            "errors": [str(exc)],
        }


async def _analyze_one_job(
    *,
    hunt_id: str,
    user_id: str,
    hunt_goal: str,
    job: JobORM,
) -> dict:
    """Run one analyzer reasoner invocation + persist the Case to EverOS."""
    task_id: Optional[str] = None
    try:
        task_id = task_registry.start_task(
            kind="analyzer_job",
            hunt_id=hunt_id,
            job_id=job.id,
            label=f"Analyzing negotiation {job.id[:8]}",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "_analyze_one_job: failed to register sub task job=%s", job.id
        )
        task_id = None

    try:
        listing_dict: dict = {}
        messages: list[dict] = []
        async with AsyncSessionLocal() as session:
            try:
                cache_rows = await session.execute(
                    select(ListingCache).where(
                        ListingCache.listing_id == job.listing_id
                    )
                )
                cache_row = cache_rows.scalars().first()
                if cache_row is not None:
                    listing_dict = dict(cache_row.raw_data or {})
                    listing_dict.setdefault("id", cache_row.listing_id)
                    listing_dict.setdefault("marketplace", cache_row.marketplace)
                    listing_dict.setdefault("title", cache_row.title or "")
                    listing_dict.setdefault(
                        "price",
                        (cache_row.price_cents / 100.0)
                        if cache_row.price_cents is not None
                        else 0.0,
                    )
                    listing_dict.setdefault("url", cache_row.url or "")
                    listing_dict.setdefault(
                        "description", cache_row.description or ""
                    )
            except Exception:  # noqa: BLE001 — best-effort lookup
                logger.exception(
                    "_analyze_one_job: listing lookup failed job=%s", job.id
                )
                listing_dict = {"id": job.listing_id}

            try:
                rows = await MessageThread.list_for_job(session, job.id)
            except Exception:  # noqa: BLE001 — best-effort lookup
                logger.exception(
                    "_analyze_one_job: transcript lookup failed job=%s", job.id
                )
                rows = []
            messages = [
                {
                    "role": r.role,
                    "text": r.text,
                    "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                }
                for r in rows
            ]

        outcome = _outcome_for_job(job, messages)
        analyzer_payload = {
            "negotiation_transcript": messages,
            "listing": listing_dict,
            "outcome": outcome,
            "target_price": float(job.target_price)
            if job.target_price is not None
            else None,
            "final_price": float(job.final_price)
            if job.final_price is not None
            else None,
            "hunt_goal": hunt_goal,
            "user_id": user_id,
        }

        try:
            analysis = await invoke_reasoner(
                "analyze_negotiation",
                analyzer_payload,
                timeout=120.0,
                raise_on_error=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "_analyze_one_job: reasoner call raised job=%s", job.id
            )
            if task_id:
                task_registry.finish_task(
                    task_id, status="errored", summary=str(exc)
                )
            return {"ok": False, "job_id": job.id, "error": str(exc)}

        if not isinstance(analysis, dict) or "error" in analysis:
            err = analysis.get("error") if isinstance(analysis, dict) else "no response"
            logger.warning(
                "_analyze_one_job: reasoner returned error job=%s err=%s",
                job.id,
                err,
            )
            if task_id:
                task_registry.finish_task(
                    task_id, status="errored", summary=str(err)
                )
            return {"ok": False, "job_id": job.id, "error": str(err)}

        # Persist the analyzed Case to EverOS.
        write_ok = await _write_analyzed_case(
            user_id=user_id,
            job_id=job.id,
            analysis=analysis,
        )
        if task_id:
            task_registry.finish_task(
                task_id,
                status="completed",
                summary=(
                    f"Wrote analyzed Case for {job.id[:8]} "
                    f"({outcome})"
                    if write_ok
                    else "Reasoner ok; EverOS write skipped"
                ),
            )
        # Phase Q — analyzer_progress per analyzed job.
        try:
            await task_registry.record_activity_async(
                hunt_id=hunt_id,
                phase="analyzer_progress",
                user_id=user_id,
                job_id=job.id,
                action_summary=(
                    f"Analyzed negotiation {job.id[:8]} ({outcome})"
                ),
                next_goal=None,
                push_to_queue=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "_analyze_one_job: analyzer_progress activity emit failed job=%s",
                job.id,
            )
        return {"ok": True, "job_id": job.id, "outcome": outcome}
    except Exception as exc:  # noqa: BLE001 — never raise
        logger.exception("_analyze_one_job: unexpected error job=%s", job.id)
        if task_id:
            task_registry.finish_task(
                task_id, status="errored", summary=str(exc)
            )
        return {"ok": False, "job_id": job.id, "error": str(exc)}


def _outcome_for_job(job: JobORM, messages: list[dict]) -> str:
    """Classify the outcome label the analyzer reasoner expects.

    - ``closed_deal``: closed job with a recorded ``final_price``.
    - ``declined``: closed job without a ``final_price`` and at least one
      buyer-agent message present (sibling decline from finalize_close).
    - ``no_response``: closed job without any seller reply at all.
    - ``abandoned``: anything else (e.g. cancelled then closed).
    """
    if job.final_price is not None:
        return "closed_deal"
    has_seller = any(
        isinstance(m, dict) and m.get("role") == "seller" for m in messages
    )
    has_buyer = any(
        isinstance(m, dict) and m.get("role") == "buyer_agent"
        for m in messages
    )
    if has_buyer and not has_seller:
        return "no_response"
    if has_buyer:
        return "declined"
    return "abandoned"


async def _write_analyzed_case(
    *, user_id: str, job_id: str, analysis: dict
) -> bool:
    """Write the structured analysis to EverOS as one assistant message.

    Returns True when the write succeeded, False on missing key / SDK /
    network error. Errors are logged but never re-raised.
    """
    if not user_id:
        return False

    settings = get_settings()
    if not settings.everos_api_key:
        logger.info(
            "_write_analyzed_case: EVEROS_API_KEY not set; skipping write job=%s",
            job_id,
        )
        return False

    try:
        from everos import EverOS  # type: ignore
    except ImportError:
        logger.warning(
            "_write_analyzed_case: everos SDK not installed; skipping job=%s",
            job_id,
        )
        return False

    session_id = f"goti-analysis-{job_id}"
    content_json = json.dumps(analysis, ensure_ascii=False)
    timestamp_ms = int(time.time() * 1000)
    messages_payload = [
        {
            "role": "assistant",
            "timestamp": timestamp_ms,
            "content": content_json,
        }
    ]

    def _call() -> bool:
        try:
            client: Any = EverOS()  # reads EVEROS_API_KEY from env
        except Exception:  # noqa: BLE001
            logger.exception(
                "_write_analyzed_case: EverOS client init failed job=%s", job_id
            )
            return False
        try:
            client.v1.memories.agent.add(
                user_id=user_id,
                session_id=session_id,
                messages=messages_payload,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "_write_analyzed_case: agent.add failed job=%s", job_id
            )
            return False
        # Trigger Skill extraction (best-effort).
        try:
            client.v1.memories.agent.flush(
                user_id=user_id, session_id=session_id
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "_write_analyzed_case: flush failed job=%s (non-fatal)", job_id
            )
        logger.info(
            "_write_analyzed_case: wrote analyzed case user=%s job=%s session=%s",
            user_id,
            job_id,
            session_id,
        )
        return True

    try:
        return await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception(
            "_write_analyzed_case: dispatch failed job=%s (non-fatal)", job_id
        )
        return False
