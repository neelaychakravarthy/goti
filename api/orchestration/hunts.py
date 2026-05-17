"""Hunt lifecycle orchestration.

A Hunt is the long-running, multi-phase asyncio coroutine that drives a
user's natural-language goal from initial input to closed deals (or to
``error`` / ``closed`` with no picks).

The lifecycle:

1. **Clarify** — invoke the ``ask_clarifying_question`` reasoner, which
   pauses via ``app.pause()`` for the user to enter their budget. The
   bridge router (``api/routes/agent_bridge.py``) turns that pause into
   a notification + DB-backed approval row. When the user POSTs to
   ``/api/approvals/{id}`` with ``feedback={"budget": ...}``, the
   approval-resolution route POSTs back to the agent webhook, the
   reasoner future resolves, and ``invoke_reasoner`` returns with the
   budget value extracted from the feedback.

2. **Discover + value** — call ``discovery.search`` (browser-agent over
   the user's logged-in marketplaces), then loop ``assess_listing`` per
   result to score target prices. Listings + valuations are cached into
   ``listings_cache`` for ``GET /api/goals/{hunt_id}/listings`` to serve.

3. **Pick** — invoke the ``pick_listings`` reasoner, which pauses with
   the ranked listings and waits for the user to select which ones to
   negotiate on. Feedback shape: ``{"picked_listing_ids": [...]}``.

4. **Negotiate** — for each picked listing, create a Job row + spawn a
   per-job lifecycle coroutine (``api/orchestration/jobs.py``
   ``run_job_lifecycle``). All run concurrently.

State lives in Postgres so it survives container restarts; lifecycle
coroutines themselves are in-memory and die on restart. Phase-level
resumption is handled via ``hunts.lifecycle_phase`` — see
``run_hunt_lifecycle`` below for the per-phase idempotency rules.
"""

from __future__ import annotations

import asyncio
import logging
import uuid as _uuid_module
from typing import Any, Optional

from sqlalchemy import select

from api import notifications as notif_queue
from api.db import AsyncSessionLocal
from api.models import (
    ApprovalQueueItem,
    Hunt,
    Job,
    ListingCache,
    Notification,
)
from api.orchestration import agents_client, jobs as orch_jobs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-process cache of {hunt_id: [{"listing": dict, "valuation": dict}, ...]}
# so the GET /api/goals/{hunt_id}/listings route can serve the same valuations
# the user is being asked to pick from. Persisted to listings_cache below
# (for cross-instance reads) but the in-process copy is the canonical reader
# while the lifecycle coroutine is alive — avoids a JSONB round-trip per
# request during the demo flow.

_HUNT_LISTINGS: dict[str, list[dict]] = {}

# Per-hunt registry of in-flight ``asyncio.Task`` coroutines (hunt
# lifecycle + each spawned job lifecycle). The DELETE endpoint cancels
# everything registered under a hunt id so a delete doesn't leave a
# dangling browser-use session burning Browserbase budget. The
# ``run_action`` try/finally ends the Browserbase session when the task
# raises ``CancelledError``.
_HUNT_TASKS: dict[str, list[asyncio.Task]] = {}


def register_hunt_task(hunt_id: str, task: asyncio.Task) -> None:
    """Record a background task so the DELETE flow can cancel it later.

    Adds a done-callback that prunes the registry entry once the task
    completes so we don't accumulate stale references to finished
    tasks (which would otherwise pile up across many hunts).
    """
    _HUNT_TASKS.setdefault(hunt_id, []).append(task)

    def _on_done(t: asyncio.Task) -> None:
        bucket = _HUNT_TASKS.get(hunt_id)
        if not bucket:
            return
        try:
            bucket.remove(t)
        except ValueError:
            pass
        if not bucket:
            _HUNT_TASKS.pop(hunt_id, None)

    task.add_done_callback(_on_done)


# Per-clarification asyncio.Event + answer slot. When the streaming
# discovery loop asks the user a question, it persists an
# ApprovalQueueItem + Notification, registers an Event keyed by the
# approval_request_id, then awaits the Event. The approvals route
# resolver looks up the Event by id and sets it with the user's
# feedback. Tracked in-memory only — a container restart while a
# clarification is pending is acceptable loss for the demo (the user
# will see the unresolved notification and can re-start the hunt).
_DISCOVERY_CLARIFY_EVENTS: dict[str, asyncio.Event] = {}
_DISCOVERY_CLARIFY_ANSWERS: dict[str, str] = {}


def deliver_discovery_clarification(approval_request_id: str, answer: str) -> bool:
    """Resolve a pending discovery clarification with the user's answer.

    Called by the approvals route when the user submits feedback on an
    approval whose ``request_payload.clarify_type ==
    "discovery_criteria"``. Returns True if the event existed (the
    discovery loop was actually waiting); False otherwise (stale event
    / wrong id).
    """
    event = _DISCOVERY_CLARIFY_EVENTS.get(approval_request_id)
    if event is None:
        return False
    _DISCOVERY_CLARIFY_ANSWERS[approval_request_id] = answer
    event.set()
    return True


async def request_discovery_clarification(
    *,
    hunt_id: str,
    user_id: str,
    question: str,
    context: str,
    timeout_seconds: float = 1800.0,
) -> str | None:
    """Pause discovery to ask the user a clarifying question; return
    their answer (or ``None`` on timeout).

    Persists an ``ApprovalQueueItem`` keyed on a fresh
    ``approval_request_id`` + a paired ``Notification`` with
    ``payload.clarify_type="discovery_criteria"``. Then awaits an
    in-process ``asyncio.Event`` that the approvals resolver sets when
    the user POSTs their feedback.

    ``timeout_seconds`` caps how long discovery waits before giving up
    — defaults to 30 minutes. On timeout the discovery loop should
    treat the result as "skip this marketplace" rather than retry.
    """
    approval_request_id = f"hunt-{hunt_id}-discover-clarify-{_uuid_module.uuid4().hex[:8]}"

    # Persist the approval + notification so the UI sees them via the
    # standard channels (sidebar dot, notifications stream, etc.).
    try:
        async with AsyncSessionLocal() as s:
            await ApprovalQueueItem.create(
                s,
                approval_request_id=approval_request_id,
                draft_text=question,
                request_payload={
                    "clarify_type": "discovery_criteria",
                    "hunt_id": hunt_id,
                    "question": question,
                    "context": context,
                },
            )
            notif = await Notification.create(
                s,
                user_id=user_id,
                kind="clarifying_question",
                title="Goti needs a quick clarification",
                body=question,
                target_href=f"/c/{hunt_id}",
                hunt_id=hunt_id,
                payload={
                    "clarify_type": "discovery_criteria",
                    "hunt_id": hunt_id,
                    "question": question,
                    "context": context,
                    "approval_request_id": approval_request_id,
                },
                approval_request_id=approval_request_id,
            )
            await s.commit()
            await notif_queue.enqueue(notif.to_event_dict())
    except Exception:  # noqa: BLE001 — persist failures are non-fatal but log
        logger.exception(
            "request_discovery_clarification: persist failed hunt=%s", hunt_id
        )
        return None

    # Wait for the user's answer.
    event = asyncio.Event()
    _DISCOVERY_CLARIFY_EVENTS[approval_request_id] = event
    try:
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                "request_discovery_clarification: hunt=%s timed out waiting "
                "for user answer after %ds",
                hunt_id,
                int(timeout_seconds),
            )
            return None
        return _DISCOVERY_CLARIFY_ANSWERS.pop(approval_request_id, None)
    finally:
        _DISCOVERY_CLARIFY_EVENTS.pop(approval_request_id, None)


def cancel_hunt_tasks(hunt_id: str) -> int:
    """Cancel every task registered for ``hunt_id``. Returns the number
    that were still running. Cleared from the registry afterwards.

    NOTE: this is fire-and-forget — the tasks' ``finally`` blocks
    (which release Browserbase sessions, close browser-use Agents,
    etc.) may still be running when this returns. For graceful
    shutdown that BLOCKS until cleanup actually finishes, callers
    should ``await cancel_hunt_tasks_async`` instead.
    """
    tasks = _HUNT_TASKS.pop(hunt_id, [])
    cancelled = 0
    for task in tasks:
        if not task.done():
            task.cancel()
            cancelled += 1
    return cancelled


async def cancel_hunt_tasks_async(
    hunt_id: str, *, timeout: float = 12.0
) -> int:
    """Graceful version of ``cancel_hunt_tasks``.

    Cancels every task, then ``awaits`` them all (bounded by
    ``timeout``) so the route only returns once each task has run its
    ``finally`` block — Browserbase sessions released, browser-use
    Agents closed, semaphore permits released.

    Returns the count of tasks that were cancelled (running at call
    time). Timeout default is 12s — enough for end_session HTTP
    roundtrip + browser_session.kill (each ~1-3s) plus headroom.
    """
    tasks = _HUNT_TASKS.pop(hunt_id, [])
    cancelled = 0
    pending: list[asyncio.Task] = []
    for task in tasks:
        if not task.done():
            task.cancel()
            cancelled += 1
            pending.append(task)
    if not pending:
        return cancelled
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "cancel_hunt_tasks_async: hunt=%s %d task(s) did not finish "
            "cleanup within %ds — leaving them detached",
            hunt_id,
            len(pending),
            int(timeout),
        )
    return cancelled


def get_cached_listings(hunt_id: str) -> list[dict]:
    """Return the cached ``{listing, valuation}`` entries for a hunt.

    Empty list if the hunt's discovery phase hasn't run yet. The shape
    matches what's passed to ``pick_listings``.
    """
    return list(_HUNT_LISTINGS.get(hunt_id, []))


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def start_hunt(
    user_id: str,
    goal_text: str,
    session,
) -> Hunt:
    """Create a Hunt row + spawn its lifecycle coroutine in the background.

    Caller commits its own session for the Hunt insert; the spawned task
    owns its own DB session lifecycle.
    """
    hunt = await Hunt.create(
        session,
        user_id=user_id,
        goal_text=goal_text,
        status="awaiting_clarification",
        lifecycle_phase="clarifying",
    )
    # Caller commits — we just need the row id to spawn the task.
    task = asyncio.create_task(_run_hunt_lifecycle_safe(hunt.id))
    register_hunt_task(hunt.id, task)
    return hunt


async def _run_hunt_lifecycle_safe(hunt_id: str) -> None:
    """Wrap ``run_hunt_lifecycle`` in a try/except + error notification.

    Every lifecycle invocation goes through here so an uncaught exception
    in a reasoner / DB / network call doesn't silently hang the hunt —
    the user sees ``status='error'`` + a notification.
    """
    try:
        await run_hunt_lifecycle(hunt_id)
    except Exception:  # noqa: BLE001 — top-level lifecycle catch
        logger.exception("hunt lifecycle errored hunt_id=%s", hunt_id)
        try:
            async with AsyncSessionLocal() as s:
                hunt = await Hunt.get(s, hunt_id)
                # Hunt should always exist (the lifecycle only ran because we
                # created the row). Fall back to "unknown" so the error
                # notification still routes somewhere honest.
                user_id = hunt.user_id if hunt else "unknown"
                await Hunt.update_status(s, hunt_id, "error")
                await Hunt.update_lifecycle_phase(s, hunt_id, "error")
                await s.commit()
            # User-facing error notification
            try:
                async with AsyncSessionLocal() as s:
                    notif = await Notification.create(
                        s,
                        user_id=user_id,
                        kind="error",
                        title="Hunt failed",
                        body="Goti's hunt lifecycle hit an unrecoverable error.",
                        target_href=f"/start?hunt_id={hunt_id}",
                        hunt_id=hunt_id,
                        payload={"hunt_id": hunt_id, "phase": "lifecycle"},
                    )
                    await s.commit()
                    await notif_queue.enqueue(notif.to_event_dict())
            except Exception:  # noqa: BLE001
                logger.exception(
                    "hunt lifecycle: failed to enqueue error notification hunt=%s",
                    hunt_id,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "hunt lifecycle: failed to mark hunt=%s as error", hunt_id
            )
        finally:
            # Cancel any sibling tasks for this hunt that might still be
            # holding semaphore permits — typically a job lifecycle the
            # user spawned via POST /api/hunts/{id}/jobs that ended up
            # wedged in browser-use. Without this, the failed hunt's
            # stuck task leaks Browserbase permits forever and the next
            # hunt the user starts shows a misleading "queued: waiting
            # for a free Browserbase session" message even though no
            # actual session is running.
            try:
                cancelled = cancel_hunt_tasks(hunt_id)
                if cancelled:
                    logger.info(
                        "hunt lifecycle: cancelled %d stuck sibling task(s) for hunt=%s",
                        cancelled,
                        hunt_id,
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "hunt lifecycle: failed to cancel sibling tasks hunt=%s",
                    hunt_id,
                )


# ---------------------------------------------------------------------------
# The lifecycle proper
# ---------------------------------------------------------------------------


async def run_hunt_lifecycle(hunt_id: str) -> None:
    """Run the full multi-phase hunt lifecycle, idempotently.

    The lifecycle reads ``lifecycle_phase`` from the DB on entry and
    skips any phase whose work is already persisted. This makes the
    coroutine safe to re-spawn on container restart — each phase is
    gated by a check against the durable side-effects it produces:

    | Phase | Skip when                                                |
    |-------|----------------------------------------------------------|
    | clarifying  | ``hunt.budget IS NOT NULL`` (clarifier resolved)   |
    | discovering | ``listings_cache`` has rows for this hunt's goal_id|
    | picking     | at least one Job exists for this hunt              |
    | negotiating | (always run; per-job lifecycles handle their own)  |

    For pause-points (clarifying, picking): if an ``approval_queue`` row
    already exists with the matching ``approval_request_id`` AND its
    ``decision IS NOT NULL``, the user has already responded — we use
    the stored feedback instead of re-invoking the reasoner. This is
    the durable resumption win: a user typing a goal, getting a
    clarifying question, then the container restarting, will see the
    SAME pending question (from the persisted ``approval_queue`` +
    ``notifications`` rows) and can still respond. When the lifecycle
    re-runs, it picks up the stored feedback and continues.

    Reasoner calls themselves are long-blocking (``timeout=3600``)
    because the bridge → user-approval → resume webhook →
    reasoner-return path can take human time. Internal valuation calls
    use a short timeout (no human in the loop).
    """
    # ---- load hunt + user_id ----
    async with AsyncSessionLocal() as s:
        hunt = await Hunt.get(s, hunt_id)
        if hunt is None:
            logger.error("run_hunt_lifecycle: hunt=%s not found", hunt_id)
            return
        user_id = hunt.user_id
        goal_text = hunt.goal_text
        persisted_budget = hunt.budget
        lifecycle_phase = hunt.lifecycle_phase

    logger.info(
        "run_hunt_lifecycle: starting hunt=%s user=%s goal=%r phase=%s",
        hunt_id,
        user_id,
        goal_text,
        lifecycle_phase,
    )

    # Terminal phases — nothing to do.
    if lifecycle_phase in ("closed", "error"):
        logger.info(
            "run_hunt_lifecycle: hunt=%s already terminal phase=%s — skipping",
            hunt_id,
            lifecycle_phase,
        )
        return

    # ---- PHASE 1: Clarify (paused for budget) ----
    # Skip if the budget is already persisted (clarifier already resolved).
    # Resumption win: if the user-facing approval row exists with a
    # decision, we use the stored feedback instead of re-pausing.
    if persisted_budget is not None and lifecycle_phase != "clarifying":
        budget = float(persisted_budget)
        logger.info(
            "run_hunt_lifecycle: hunt=%s clarify phase already complete budget=%s",
            hunt_id,
            budget,
        )
    else:
        budget = await _resolve_or_invoke_clarifier(
            hunt_id=hunt_id, user_id=user_id, goal_text=goal_text
        )
        async with AsyncSessionLocal() as s:
            if budget is not None:
                await Hunt.update_budget(s, hunt_id, budget)
            await Hunt.update_status(s, hunt_id, "discovering")
            await Hunt.update_lifecycle_phase(s, hunt_id, "discovering")
            await s.commit()

    # ---- PHASE 2: Discovery + valuation ----
    # Skip if listings_cache already has rows for this hunt (discovery
    # already ran). Re-load valuations from the cache when skipping so
    # the picker reasoner gets the same data on retry.
    cached_valuations = get_cached_listings(hunt_id)
    if not cached_valuations:
        cached_valuations = await _load_cached_valuations(hunt_id, budget)

    if cached_valuations and lifecycle_phase in (
        "picking",
        "negotiating",
        "closed",
        "error",
    ):
        valuations = cached_valuations
        logger.info(
            "run_hunt_lifecycle: hunt=%s discovery already complete cached=%d",
            hunt_id,
            len(valuations),
        )
        _HUNT_LISTINGS[hunt_id] = valuations
    else:
        from api.orchestration import tasks as _task_registry

        discovery_task_id = None
        try:
            discovery_task_id = _task_registry.start_task(
                kind="discovery",
                hunt_id=hunt_id,
                label="Searching marketplaces",
                user_id=user_id,
            )
        except Exception:  # noqa: BLE001
            discovery_task_id = None
        try:
            valuations = await _run_discovery_and_valuation(
                hunt_id=hunt_id,
                user_id=user_id,
                goal_text=goal_text,
                budget=budget,
            )
            if discovery_task_id:
                _task_registry.finish_task(
                    discovery_task_id,
                    status="completed",
                    summary=f"Surfaced {len(valuations)} candidate(s)",
                )
        except Exception as exc:  # noqa: BLE001
            if discovery_task_id:
                _task_registry.finish_task(
                    discovery_task_id,
                    status="errored",
                    summary=str(exc),
                )
            raise
        _HUNT_LISTINGS[hunt_id] = valuations

        # If discovery returned nothing, don't proceed to the picker — there's
        # nothing for the user to pick. Mark error so the UI surfaces the problem.
        if not valuations:
            logger.warning(
                "run_hunt_lifecycle: hunt=%s discovery returned 0 listings — "
                "marking error",
                hunt_id,
            )
            async with AsyncSessionLocal() as s:
                await Hunt.update_status(s, hunt_id, "error")
                await Hunt.update_lifecycle_phase(s, hunt_id, "error")
                await s.commit()
            await _emit_notification(
                user_id=user_id,
                hunt_id=hunt_id,
                kind="error",
                title="No listings found",
                body=(
                    "Goti's discovery returned 0 listings. Make sure you've "
                    "linked at least one marketplace via the onboarding flow "
                    "(Browserbase + browser-agent need a logged-in session)."
                ),
                target_href=f"/start?hunt_id={hunt_id}",
                payload={"hunt_id": hunt_id, "phase": "discovery"},
            )
            return

        async with AsyncSessionLocal() as s:
            await Hunt.update_status(s, hunt_id, "awaiting_picks")
            await Hunt.update_lifecycle_phase(s, hunt_id, "picking")
            await s.commit()

    # ---- PHASE 3: Candidates ready; user spawns negotiations on demand ----
    # The streaming discovery loop emitted ``listings_found``
    # notifications for each candidate as it arrived. The user picks
    # negotiations via ``POST /api/hunts/{id}/jobs`` (see
    # ``api/routes/hunts.py``); no global picker pause anymore — the
    # hunt just sits in ``awaiting_picks`` until a deal closes or the
    # user explicitly stops it.
    #
    # The only thing left for the lifecycle to do is re-spawn job
    # coroutines on resumption — if the container restarted while jobs
    # were mid-negotiation, the per-job lifecycles need to come back.
    existing_jobs = await _list_jobs_for_hunt(hunt_id)
    if existing_jobs and lifecycle_phase == "negotiating":
        # Jobs exist + lifecycle was already in negotiating phase →
        # re-spawn the per-job coroutines for any non-terminal jobs.
        val_by_id = {v["listing"]["id"]: v for v in valuations}
        for job in existing_jobs:
            if job.status in ("closed", "cancelled"):
                continue
            entry = val_by_id.get(job.listing_id)
            if entry is None:
                logger.warning(
                    "run_hunt_lifecycle: resume — job=%s listing=%s missing "
                    "valuation, skipping",
                    job.id,
                    job.listing_id,
                )
                continue
            logger.info(
                "run_hunt_lifecycle: resuming job=%s under hunt=%s",
                job.id,
                hunt_id,
            )
            resumed_task = asyncio.create_task(
                orch_jobs.run_job_lifecycle_safe(
                    job_id=job.id,
                    listing=entry["listing"],
                    valuation=entry["valuation"],
                )
            )
            register_hunt_task(hunt_id, resumed_task)
        return

    # No picker pause. The hunt now sits in ``awaiting_picks`` until
    # either (a) the user clicks "Start negotiation" on a candidate via
    # ``POST /api/hunts/{id}/jobs`` — which spawns its own job
    # lifecycle — or (b) a deal closes and the close-deal route flips
    # the hunt to ``closed``. Either way the lifecycle coroutine's job
    # here is done.
    logger.info(
        "run_hunt_lifecycle: hunt=%s discovery complete (%d candidates); "
        "awaiting user negotiate picks",
        hunt_id,
        len(valuations),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_budget(clarifier_response: Any) -> Optional[float]:
    """Extract a numeric budget from the clarifier's post-resume return.

    The clarifier reasoner returns either ``{"budget": <num>}`` (the new
    paused shape) or ``{"clarifying_answer": <num>}`` (a tolerated alt
    shape). On any parse failure return None — the hunt lifecycle treats
    a missing budget as "use the listing's asking price as the anchor".
    """
    if not isinstance(clarifier_response, dict):
        return None
    candidate = (
        clarifier_response.get("budget")
        or clarifier_response.get("clarifying_answer")
        or clarifier_response.get("value")
        or clarifier_response.get("answer")
    )
    if candidate is None:
        return None
    if isinstance(candidate, (int, float)):
        return float(candidate)
    if isinstance(candidate, str):
        cleaned = candidate.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _coerce_picked_ids(pick_response: Any) -> list[str]:
    """Extract the picked-listing IDs from the pick_listings reasoner."""
    if not isinstance(pick_response, dict):
        return []
    ids = pick_response.get("picked_listing_ids") or pick_response.get("listing_ids")
    if not isinstance(ids, list):
        return []
    return [str(i) for i in ids if isinstance(i, (str, int))]


def _valuation_fallback(listing: Any, budget: Optional[float]) -> dict:
    """Return a safe valuation dict so the lifecycle never blocks on a
    reasoner failure. ``target_price`` defaults to the listing price."""
    try:
        price = float(listing.price) if hasattr(listing, "price") else 0.0
    except (TypeError, ValueError):
        price = 0.0
    return {
        "fair_price_estimate": price,
        "walk_away_price": float(budget) if budget else price,
        "target_price": price,
        "reasoning": "valuation unavailable; fell back to listing's asking price.",
    }


def _coerce_uuid(value: str | _uuid_module.UUID) -> _uuid_module.UUID:
    """Convert a hex/string hunt id to a ``uuid.UUID``.

    ``listings_cache.goal_id`` is declared as Postgres ``UUID(as_uuid=
    True)`` — its bind processor calls ``.hex`` on the value, which
    raises on plain strings. The hunt lifecycle passes ``hunt_id`` as a
    string throughout, so we centralise the coercion here.
    """
    return value if isinstance(value, _uuid_module.UUID) else _uuid_module.UUID(value)


async def _cache_listings(hunt_id: str, listings: list) -> None:
    """Persist discovery results to ``listings_cache`` keyed by ``goal_id=hunt_id``.

    Each row is keyed on ``(marketplace, listing_id)``; we use an upsert
    pattern via SQLAlchemy: try insert, on integrity error update fields.
    Errors are swallowed (cache is read-best-effort).
    """
    if not listings:
        return
    try:
        async with AsyncSessionLocal() as s:
            for li in listings:
                try:
                    row = await s.get(
                        ListingCache, {"marketplace": li.marketplace, "listing_id": li.id}
                    )
                except Exception:  # noqa: BLE001 — composite-PK get can mis-shape under SQLite
                    row = None
                if row is None:
                    row = ListingCache(
                        marketplace=li.marketplace,
                        listing_id=li.id,
                        title=li.title,
                        description=li.description,
                        price_cents=int(li.price * 100) if li.price is not None else None,
                        url=li.url,
                        raw_data=li.model_dump(),
                        goal_id=_coerce_uuid(hunt_id),
                    )
                    s.add(row)
                else:
                    row.title = li.title
                    row.description = li.description
                    row.price_cents = (
                        int(li.price * 100) if li.price is not None else None
                    )
                    row.url = li.url
                    row.raw_data = li.model_dump()
                    row.goal_id = _coerce_uuid(hunt_id)
            await s.commit()
    except Exception:  # noqa: BLE001
        logger.exception("_cache_listings: persist failed hunt=%s (non-fatal)", hunt_id)


# ---------------------------------------------------------------------------
# Idempotency + resumption helpers
# ---------------------------------------------------------------------------


def _clarifier_approval_id(hunt_id: str) -> str:
    """Stable approval_request_id for the clarifier pause.

    Mirrors the format the clarifier reasoner uses when calling
    ``app.pause()`` — keeping them in sync lets the lifecycle look up
    a pre-decided approval row when the user already answered.
    """
    return f"hunt-{hunt_id}-budget"


def _picker_approval_id(hunt_id: str) -> str:
    """Stable approval_request_id for the picker pause."""
    return f"hunt-{hunt_id}-pick"


async def _resolve_or_invoke_clarifier(
    *, hunt_id: str, user_id: str, goal_text: str
) -> Optional[float]:
    """Either return the user's already-decided budget or invoke the clarifier.

    Resumption win: if the user typed a budget and then the container
    restarted before the lifecycle resumed, the approval row already
    has the decision. We read it instead of producing a duplicate
    pause notification.
    """
    approval_id = _clarifier_approval_id(hunt_id)
    async with AsyncSessionLocal() as s:
        existing = await ApprovalQueueItem.get_by_approval_request_id(s, approval_id)
        if existing is not None and existing.decision is not None:
            feedback = existing.feedback or {}
            budget = _coerce_budget(feedback) or _coerce_budget(
                {"budget": feedback.get("budget")}
            )
            logger.info(
                "run_hunt_lifecycle: hunt=%s clarifier resumed from stored "
                "decision budget=%s",
                hunt_id,
                budget,
            )
            return budget

    # No stored decision — invoke the reasoner, which pauses for the user.
    clarifier_response = await agents_client.invoke_reasoner(
        "ask_clarifying_question",
        {
            "goal": goal_text,
            "hunt_id": hunt_id,
            "user_id": user_id,
        },
        timeout=3600.0,
        raise_on_error=False,
    )
    return _coerce_budget(clarifier_response)


async def _resolve_or_invoke_picker(
    *, hunt_id: str, user_id: str, valuations: list[dict]
) -> list[str]:
    """Either return the user's already-decided picks or invoke the picker."""
    approval_id = _picker_approval_id(hunt_id)
    async with AsyncSessionLocal() as s:
        existing = await ApprovalQueueItem.get_by_approval_request_id(s, approval_id)
        if existing is not None and existing.decision is not None:
            feedback = existing.feedback or {}
            picked = _coerce_picked_ids(feedback)
            logger.info(
                "run_hunt_lifecycle: hunt=%s picker resumed from stored "
                "decision picks=%d",
                hunt_id,
                len(picked),
            )
            return picked

    pick_response = await agents_client.invoke_reasoner(
        "pick_listings",
        {
            "hunt_id": hunt_id,
            "listings_with_valuations": valuations,
            "user_id": user_id,
        },
        timeout=3600.0,
        raise_on_error=False,
    )
    return _coerce_picked_ids(pick_response)


_MAX_PER_MARKETPLACE = 5


async def _run_discovery_and_valuation(
    *, hunt_id: str, user_id: str, goal_text: str, budget: Optional[float]
) -> list[dict]:
    """Stream candidates from each linked marketplace, one at a time.

    Each iteration is a SHORT browser-use task
    (``actions.search_one_listing``) — fits comfortably inside a single
    Browserbase session so a mid-flight HTTP 410 can lose at most one
    candidate. As soon as a listing comes back we:

    1. Persist it to ``listings_cache`` so resumption / the
       picker / the UI can see it immediately.
    2. Run valuation (LLM call) so the surfaced candidate already
       carries fair_price + walk_away + target_price numbers.
    3. Emit a ``listings_found`` notification (per-listing) so the
       SSE-subscribed UI shows the candidate live, before the rest of
       discovery finishes.

    Per linked marketplace: caps at ``_MAX_PER_MARKETPLACE`` listings.
    The loop checks ``Hunt.status`` every iteration and exits cleanly
    when the hunt is closed (e.g. user closed a deal mid-discovery).
    """
    from api.integrations.browser_agent import actions as agent_actions
    from api.models import IntegrationAccountRow

    async with AsyncSessionLocal() as s:
        linked_rows = await IntegrationAccountRow.list_active_for_user(
            s, user_id
        )
    linked_providers = [r.provider for r in linked_rows]
    context_id = next(
        (r.browserbase_context_id for r in linked_rows if r.browserbase_context_id),
        None,
    )
    if not linked_providers or not context_id:
        logger.warning(
            "run_hunt_lifecycle: hunt=%s user has no linked marketplaces; "
            "skipping discovery",
            hunt_id,
        )
        return []

    valuations: list[dict] = []
    # ``seen`` carries ``{id, title, url}`` per already-surfaced listing
    # so the agent can recognise dupes at the title-scan stage rather
    # than burning a click to read the post id on a detail page.
    seen: list[dict] = []
    per_marketplace_start: dict[str, int] = {m: 0 for m in linked_providers}

    # Rehydrate state from listings_cache so a resumed hunt picks up
    # where it left off instead of re-finding the same candidates.
    # Each row in the cache for this hunt is one already-surfaced
    # listing; we feed its id back as an exclude (so the agent doesn't
    # return it again) AND count it against the per-marketplace cap.
    try:
        async with AsyncSessionLocal() as s:
            existing = await s.execute(
                select(ListingCache).where(
                    ListingCache.goal_id == _coerce_uuid(hunt_id)
                )
            )
            existing_rows = list(existing.scalars().all())
        for row in existing_rows:
            seen.append(
                {
                    "id": row.listing_id,
                    "title": row.title or "",
                    "url": row.url or "",
                }
            )
            if row.marketplace in per_marketplace_start:
                per_marketplace_start[row.marketplace] += 1
            # Rebuild a minimal valuation entry so downstream code
            # (notifications, BATNA context) sees the same shape it
            # would have on a fresh run.
            listing_dict = dict(row.raw_data or {})
            listing_dict.setdefault("id", row.listing_id)
            listing_dict.setdefault("marketplace", row.marketplace)
            listing_dict.setdefault("title", row.title or "")
            listing_dict.setdefault(
                "price",
                (row.price_cents / 100.0) if row.price_cents is not None else 0.0,
            )
            valuations.append({"listing": listing_dict, "valuation": {}})
    except Exception:  # noqa: BLE001 — non-fatal rehydration
        logger.exception(
            "streaming discovery: rehydrate from listings_cache failed "
            "hunt=%s — starting from empty state",
            hunt_id,
        )

    for marketplace in linked_providers:
        per_marketplace = per_marketplace_start.get(marketplace, 0)
        # Fresh Browserbase session per iteration. We previously tried
        # reusing one session across all 5 iterations to skip the
        # initial navigate, but browser-use's Agent class doesn't play
        # nicely with shared BrowserSessions — the second iteration's
        # Agent would fail with "Expected at least one handler to
        # return a non-None result" and discovery would stop at 1
        # listing per marketplace. Reverted to fresh-per-iteration:
        # slower (one navigate-from-about:blank per iteration) but
        # actually completes the full _MAX_PER_MARKETPLACE loop.
        try:
            # Stop after _MAX_PER_MARKETPLACE; also stop the inner
            # loop early when search_one_listing returns None (no more
            # matches).
            while per_marketplace < _MAX_PER_MARKETPLACE:
                # Cooperative cancellation — hunt.status flips to "closed"
                # when the user closes a deal, or "paused" when the user
                # explicitly pauses. Exit cleanly so we don't keep
                # burning sessions on a settled / paused hunt.
                async with AsyncSessionLocal() as s:
                    hunt = await Hunt.get(s, hunt_id)
                if hunt is None or hunt.status in ("closed", "error", "paused"):
                    logger.info(
                        "run_hunt_lifecycle: hunt=%s exiting streaming "
                        "discovery (status=%s)",
                        hunt_id,
                        getattr(hunt, "status", "<missing>"),
                    )
                    return valuations

                try:
                    listing = await agent_actions.search_one_listing(
                        context_id=context_id,
                        query=goal_text,
                        marketplace=marketplace,
                        exclude=seen,
                        hunt_id=hunt_id,
                        # ``session=None`` triggers fresh-per-iteration in
                        # ``run_action``. See comment above the loop for the
                        # browser-use reuse-incompatibility rationale.
                    )
                except Exception as exc:  # noqa: BLE001
                    # Browserbase quota exhaustion = unrecoverable for this
                    # session; bail out with a dedicated notification so
                    # the UI can render an "upgrade Browserbase" banner
                    # instead of a generic empty-listings error.
                    from api.integrations.browserbase.client import (
                        BrowserbaseQuotaExhausted,
                    )

                    if isinstance(exc, BrowserbaseQuotaExhausted):
                        logger.warning(
                            "streaming discovery: Browserbase quota exhausted "
                            "hunt=%s — stopping",
                            hunt_id,
                        )
                        await _emit_notification(
                            user_id=user_id,
                            hunt_id=hunt_id,
                            kind="error",
                            title="Browserbase quota exhausted",
                            body=(
                                "Goti can't mint new browser sessions — your "
                                "Browserbase free-tier monthly minutes ran out. "
                                "Upgrade your plan at "
                                "https://browserbase.com/plans (or wait for "
                                "the monthly reset) then retry."
                            ),
                            target_href=f"/c/{hunt_id}",
                            payload={
                                "hunt_id": hunt_id,
                                "code": "browserbase_quota_exhausted",
                                "upgrade_url": "https://browserbase.com/plans",
                            },
                        )
                        async with AsyncSessionLocal() as s:
                            await Hunt.update_status(s, hunt_id, "error")
                            await Hunt.update_lifecycle_phase(s, hunt_id, "error")
                            await s.commit()
                        return valuations
                    # Anything else — log + bail this marketplace, move to
                    # the next one rather than killing the whole hunt.
                    logger.exception(
                        "streaming discovery: marketplace=%s search failed; "
                        "skipping",
                        marketplace,
                    )
                    listing = None
                # Clarification request from the agent. Pause discovery,
                # ask the user, fold their answer into ``goal_text`` for
                # subsequent iterations + retry the current marketplace
                # iteration with the refined criteria. No
                # ``per_marketplace`` increment because we didn't actually
                # surface a listing.
                from api.integrations.browser_agent.actions import (
                    ClarificationRequest as _ClarificationRequest,
                )

                if isinstance(listing, _ClarificationRequest):
                    logger.info(
                        "streaming discovery: hunt=%s agent requested "
                        "clarification: %s",
                        hunt_id,
                        listing.question,
                    )
                    answer = await request_discovery_clarification(
                        hunt_id=hunt_id,
                        user_id=user_id,
                        question=listing.question,
                        context=listing.context,
                    )
                    if not answer:
                        # User didn't answer in time — skip this marketplace.
                        logger.warning(
                            "streaming discovery: hunt=%s clarification "
                            "timed out / no answer; skipping marketplace=%s",
                            hunt_id,
                            marketplace,
                        )
                        break
                    # Fold the answer into the goal text the agent sees
                    # from now on. The agent will incorporate it in the
                    # next iteration's evaluation.
                    goal_text = (
                        f"{goal_text}\n\nUser clarification: "
                        f"Q: {listing.question}\nA: {answer}"
                    )
                    logger.info(
                        "streaming discovery: hunt=%s clarification received, "
                        "refined goal_text length=%d",
                        hunt_id,
                        len(goal_text),
                    )
                    # Retry the current iteration with the refined criteria
                    # — don't ``break``, don't ``per_marketplace +=`` either.
                    continue

                if listing is None:
                    # No more matches on this marketplace — move on to the
                    # next one in linked_providers.
                    logger.info(
                        "run_hunt_lifecycle: hunt=%s marketplace=%s exhausted at "
                        "%d listings",
                        hunt_id,
                        marketplace,
                        per_marketplace,
                    )
                    break

                seen.append(
                    {
                        "id": listing.id,
                        "title": listing.title or "",
                        "url": listing.url or "",
                    }
                )
                per_marketplace += 1

                # Persist immediately so the UI / resumption see it.
                await _cache_listings(hunt_id, [listing])

                # Value it (LLM call). Failures degrade to a fallback so a
                # transient model glitch never blocks the candidate.
                try:
                    valuation = await agents_client.invoke_reasoner(
                        "assess_listing",
                        {
                            "listing": listing.model_dump(),
                            "user_budget": budget,
                            "user_id": user_id,
                        },
                        timeout=60.0,
                        raise_on_error=False,
                    )
                    if not isinstance(valuation, dict) or "error" in valuation:
                        valuation = _valuation_fallback(listing, budget)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "run_hunt_lifecycle: valuation failed listing=%s",
                        listing.id,
                    )
                    valuation = _valuation_fallback(listing, budget)
                valuations.append(
                    {"listing": listing.model_dump(), "valuation": valuation}
                )

                # Live notification — the SSE-subscribed UI renders this as
                # a new candidate the user can immediately negotiate on.
                await _emit_notification(
                    user_id=user_id,
                    hunt_id=hunt_id,
                    kind="listings_found",
                    title=f"Candidate: {listing.title or 'untitled'}",
                    body=(
                        f"{marketplace} · ${listing.price:.0f} · "
                        f"target ${valuation.get('target_price', 0):.0f}"
                        if isinstance(listing.price, (int, float))
                        else f"{marketplace}"
                    ),
                    target_href=f"/c/{hunt_id}",
                    payload={
                        "hunt_id": hunt_id,
                        "listing": listing.model_dump(),
                        "valuation": valuation,
                    },
                )
                # Phase Q — also backfill a ``listing_discovered`` activity
                # row so the chat's initial hydration captures every
                # candidate, not just the ones surfaced during the
                # currently-mounted SSE session. ``push_to_queue=False``
                # because the listings_found notification above already
                # delivered the live event — emitting both would
                # duplicate the chat tile.
                # Phase Q listing_discovered activity row — inline
                # await so the write is serialized with the
                # surrounding discovery loop's session work AND the
                # _ACTIVITY_WRITE_LOCK in tasks.py (which guards
                # against analyzer/task-registry parallel writers).
                try:
                    from api.orchestration import tasks as _task_registry

                    await _task_registry.record_activity_async(
                        hunt_id=hunt_id,
                        phase="listing_discovered",
                        user_id=user_id,
                        action_summary=(
                            f"{listing.title or 'untitled'} · {marketplace}"
                        ),
                        next_goal=(
                            f"${listing.price:.0f} → target "
                            f"${valuation.get('target_price', 0):.0f}"
                            if isinstance(listing.price, (int, float))
                            else None
                        ),
                        url=getattr(listing, "url", None),
                        push_to_queue=False,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "_run_discovery_and_valuation: listing_discovered "
                        "activity emit failed hunt=%s",
                        hunt_id,
                    )
                # Yield cooperatively so concurrent HTTP requests can
                # interleave between iterations — otherwise on SQLite the
                # streaming commits and the API commits can race.
                await asyncio.sleep(0)
        finally:
            # Each ``search_one_listing`` call manages its own session
            # lifecycle now (fresh-per-iteration). No marketplace-level
            # cleanup needed; the try/finally remains as scaffolding for
            # future per-marketplace state.
            pass

    # Keep the in-process cache populated so resumption helpers see the
    # streamed candidates without re-reading the DB.
    _HUNT_LISTINGS[hunt_id] = valuations

    # Discovery finished naturally (cap hit or all marketplaces
    # exhausted). Emit a summary notification so the user knows
    # nothing more is coming and they can start picking. The
    # ``not valuations`` empty-case has its own error notification
    # emitted by the calling lifecycle layer; here we only celebrate
    # the success path.
    if valuations:
        try:
            await _emit_notification(
                user_id=user_id,
                hunt_id=hunt_id,
                kind="info",
                title="Discovery complete",
                body=(
                    f"Goti finished searching with "
                    f"{len(valuations)} candidate"
                    f"{'s' if len(valuations) != 1 else ''} surfaced. "
                    "Click 'Start negotiation' on any of them when "
                    "you're ready."
                ),
                target_href=f"/c/{hunt_id}",
                payload={
                    "hunt_id": hunt_id,
                    "candidate_count": len(valuations),
                    "kind_tag": "discovery_complete",
                },
            )
        except Exception:  # noqa: BLE001 — notification is best-effort
            logger.exception(
                "streaming discovery: hunt=%s failed to emit "
                "discovery-complete notification",
                hunt_id,
            )

    return valuations


async def _load_cached_valuations(
    hunt_id: str, budget: Optional[float]
) -> list[dict]:
    """Rebuild ``valuations`` from ``listings_cache`` rows for this hunt.

    Used on resumption when the in-process cache is empty but discovery
    already persisted the listings. Valuations are re-synthesized from
    the raw cached data + a fallback per-listing valuation. This is good
    enough for the picker pause — we don't want to re-burn Anthropic
    tokens valuing the same listings.
    """
    try:
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                select(ListingCache).where(
                    ListingCache.goal_id == _coerce_uuid(hunt_id)
                )
            )
            rows = list(result.scalars().all())
    except Exception:  # noqa: BLE001
        logger.exception(
            "_load_cached_valuations: DB read failed hunt=%s (non-fatal)", hunt_id
        )
        return []

    if not rows:
        return []

    valuations: list[dict] = []
    for row in rows:
        listing_dict = dict(row.raw_data or {})
        listing_dict.setdefault("id", row.listing_id)
        listing_dict.setdefault("marketplace", row.marketplace)
        listing_dict.setdefault("title", row.title or "")
        listing_dict.setdefault(
            "price",
            (row.price_cents / 100.0) if row.price_cents is not None else 0.0,
        )

        class _PriceShim:
            """Tiny shim so ``_valuation_fallback`` can read ``.price``."""

            def __init__(self, p: float) -> None:
                self.price = p

        fb_val = _valuation_fallback(
            _PriceShim(listing_dict.get("price", 0.0) or 0.0), budget
        )
        valuations.append({"listing": listing_dict, "valuation": fb_val})
    return valuations


async def _list_jobs_for_hunt(hunt_id: str) -> list:
    """Return persisted Job rows linked to ``hunt_id`` (resumption check)."""
    try:
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                select(Job).where(Job.hunt_id == hunt_id)
            )
            return list(result.scalars().all())
    except Exception:  # noqa: BLE001
        logger.exception("_list_jobs_for_hunt: DB read failed hunt=%s", hunt_id)
        return []


async def _get_pick_decision(hunt_id: str) -> Optional[str]:
    """Return the user's recorded decision for this hunt's pick approval, if any.

    ``None`` means the pause never resolved (the user never acted on the
    pick prompt). ``"approve"`` / ``"reject"`` mirror the values written by
    the approval-resolution route.
    """
    approval_id = _picker_approval_id(hunt_id)
    try:
        async with AsyncSessionLocal() as s:
            row = await ApprovalQueueItem.get_by_approval_request_id(s, approval_id)
            if row is None:
                return None
            return row.decision
    except Exception:  # noqa: BLE001
        logger.exception(
            "_get_pick_decision: DB read failed hunt=%s (treating as None)",
            hunt_id,
        )
        return None


async def _emit_notification(
    *,
    user_id: str,
    hunt_id: str,
    kind: str,
    title: str,
    body: str,
    target_href: str,
    payload: dict,
) -> None:
    """Create a Notification row + enqueue it onto the SSE channel.

    Centralised so error sites don't each duplicate the create+commit+enqueue
    dance. Swallows + logs any persistence / queue errors so a notification
    failure never breaks the surrounding lifecycle flow.
    """
    try:
        async with AsyncSessionLocal() as s:
            notif = await Notification.create(
                s,
                user_id=user_id,
                kind=kind,
                title=title,
                body=body,
                target_href=target_href,
                hunt_id=hunt_id,
                payload=payload,
            )
            await s.commit()
            await notif_queue.enqueue(notif.to_event_dict())
    except Exception:  # noqa: BLE001
        logger.exception(
            "_emit_notification: failed to emit %s notification hunt=%s",
            kind,
            hunt_id,
        )
