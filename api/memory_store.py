"""EverOS memory-store wrapper.

EverOS SDK is sync; we wrap calls in `asyncio.to_thread()` so they don't
block the FastAPI event loop.

Exposes:
- ``list_cases`` / ``list_skills`` — read APIs for the Memory Bank view.
- ``write_case_on_completion`` — writes a full negotiation transcript
  to EverOS when a job closes, then triggers Skill extraction via
  ``client.v1.memories.agent.flush(...)``.

All graceful-degrade: on missing key / SDK / network error, the read
APIs return ``[]`` and the write path swallows the error.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from api.config import get_settings
from api.contracts import Case, Skill

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from api.models import Job as JobORM

logger = logging.getLogger(__name__)

# Imported lazily inside helpers so a missing dep / missing key doesn't crash
# module import (graceful-degradation requirement from the plan).
_client_cache: Any | None = None


def _get_client() -> Any | None:
    """Lazily build an EverOS client. Returns None if not configured."""
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    settings = get_settings()
    if not settings.everos_api_key:
        logger.warning("EVEROS_API_KEY not set; memory writes will be skipped.")
        return None
    try:
        from everos import EverOS  # type: ignore
    except ImportError:
        logger.warning("everos SDK not installed; memory writes will be skipped.")
        return None
    try:
        _client_cache = EverOS()  # reads EVEROS_API_KEY from env
        return _client_cache
    except Exception:  # noqa: BLE001 — keep startup tolerant
        logger.exception("Failed to initialize EverOS client.")
        return None


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def write_case(
    goal: str,
    clarifying_question: str,
    user_id: str | None = None,
) -> None:
    """Fire-and-forget: append a 2-message Case to EverOS.

    ``user_id`` is the canonical owner identifier (a ``str(User.id)``
    UUID string). When None, the write is skipped so unauthenticated
    writes never silently mix into a real user's memory.

    Logs and swallows errors so a missing/broken EverOS never breaks /api/goals.
    """
    if not user_id:
        logger.info("Skipping EverOS write_case (no user_id provided).")
        return
    client = _get_client()
    if client is None:
        logger.info("Skipping EverOS write_case (client unavailable).")
        return

    session_id = f"goal-clarification-{int(time.time())}"
    messages = [
        {"role": "user", "timestamp": _now_iso(), "content": goal},
        {"role": "assistant", "timestamp": _now_iso(), "content": clarifying_question},
    ]

    def _call() -> None:
        try:
            client.v1.memories.agent.add(
                user_id=user_id,
                session_id=session_id,
                messages=messages,
            )
            logger.info(
                "EverOS memories.agent.add ok user=%s session=%s msgs=%d",
                user_id,
                session_id,
                len(messages),
            )
        except Exception:  # noqa: BLE001
            logger.exception("EverOS write_case failed (non-fatal).")

    try:
        await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception("EverOS write_case dispatch failed (non-fatal).")


# ---------------------------------------------------------------------------
# Read APIs — Memory Bank


def _parse_dt(value: Any) -> datetime:
    """Coerce an EverOS ``timestamp`` field into a tz-aware datetime.

    EverOS returns timestamps either as ISO-8601 strings or epoch seconds
    (per the SDK docs / our observations). Falls back to ``now()`` on
    unparseable input so the route never 500s on weird data.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return datetime.now(tz=timezone.utc)
    if isinstance(value, str):
        try:
            # Tolerate trailing 'Z' (Python <3.11 didn't accept it natively).
            cleaned = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(cleaned)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


def _parse_analyzer_content(content_raw: Any) -> dict | None:
    """Try to parse the analyzer's JSON content blob.

    The Phase G' analyzer writes a single assistant message whose
    ``content`` is ``json.dumps({what_worked, what_didnt, key_moments,
    tactical_lessons, category, region, confidence, outcome})``. EverOS
    surfaces this back on the Case as a ``content`` / ``messages``
    field. Returns the parsed dict on success, None on any parse
    failure — callers then fall back to the legacy ``summary`` /
    ``approach`` extraction so back-compat with older transcript-shaped
    Cases is preserved.
    """
    import json as _json

    candidates: list[Any] = []
    if isinstance(content_raw, str):
        candidates.append(content_raw)
    elif isinstance(content_raw, dict):
        return content_raw
    elif isinstance(content_raw, list):
        # EverOS sometimes surfaces ``messages`` as the list of agent
        # messages; pluck the last assistant content.
        for entry in reversed(content_raw):
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            if role not in ("assistant", None):
                continue
            inner = entry.get("content")
            if isinstance(inner, str):
                candidates.append(inner)
                break

    for cand in candidates:
        if not isinstance(cand, str):
            continue
        text = cand.strip()
        if not text or not (text.startswith("{") or text.startswith("[")):
            continue
        try:
            parsed = _json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _extract_analyzer_payload(item: dict) -> dict | None:
    """Try every known content field for an embedded analyzer JSON blob."""
    for key in ("content", "messages", "agent_messages", "message"):
        parsed = _parse_analyzer_content(item.get(key))
        if parsed is not None:
            return parsed
    return None


def _case_from_dict(item: dict, default_user_id: str) -> Case | None:
    """Defensively map an EverOS agent_case item to a ``Case``.

    Returns None if the item is too malformed to map at all (no id).
    Falls back to the legacy transcript-shaped Case format when the
    analyzer's JSON ``content`` field isn't present or doesn't parse.
    """
    if not isinstance(item, dict):
        return None
    case_id = item.get("id") or item.get("case_id") or item.get("session_id")
    if not isinstance(case_id, str) or not case_id:
        return None

    # Try the analyzer JSON shape first (Phase G' write format).
    analyzer = _extract_analyzer_payload(item)

    task_intent = item.get("task_intent") or item.get("title") or ""
    approach = item.get("approach") or item.get("summary") or ""

    final_price = item.get("final_price") or item.get("price")
    if isinstance(final_price, str):
        try:
            final_price = float(final_price.replace("$", "").replace(",", ""))
        except ValueError:
            final_price = None
    elif not isinstance(final_price, (int, float)):
        final_price = None

    outcome = item.get("outcome")
    # Pull from analyzer payload when EverOS doesn't surface the field
    # at the top level (analyzer writes outcome inside the content JSON).
    if outcome is None and analyzer is not None:
        outcome = analyzer.get("outcome")
    if outcome not in {"closed_deal", "abandoned", "no_response", "declined", None}:
        outcome = None
    # The Case contract still rejects "declined" — coerce it to
    # "abandoned" so the response model validates while the underlying
    # analyzer JSON keeps the precise label.
    contract_outcome = (
        "abandoned" if outcome == "declined" else outcome
    )

    category = item.get("category")
    if (category is None or category == "") and analyzer is not None:
        category = analyzer.get("category") or None
    region = item.get("region")
    if (region is None or region == "") and analyzer is not None:
        region = analyzer.get("region") or None

    # Synthesise a Case ``title`` + ``summary`` from the analyzer JSON
    # when present so the Memory page displays the structured tactics
    # without bespoke per-Case wiring. The detail view reads the JSON
    # back separately for the full structured render.
    if analyzer is not None:
        if not task_intent:
            cat = str(analyzer.get("category") or "").strip()
            task_intent = f"{cat} negotiation" if cat else "Negotiation analysis"
        if not approach:
            worked = analyzer.get("what_worked") or []
            if isinstance(worked, list) and worked:
                first = next(
                    (str(w).strip() for w in worked if isinstance(w, str) and w.strip()),
                    "",
                )
                approach = first or approach

    try:
        return Case(
            id=str(case_id),
            user_id=str(item.get("user_id") or default_user_id),
            title=str(task_intent)[:80] or "untitled case",
            summary=str(approach)[:200],
            outcome=contract_outcome,  # type: ignore[arg-type]
            final_price=final_price,
            category=category,
            region=region,
            created_at=_parse_dt(item.get("timestamp") or item.get("created_at")),
        )
    except Exception:  # noqa: BLE001 — defensive
        logger.exception("memory_store: case mapping failed for item=%r", item)
        return None


def _skill_from_dict(item: dict) -> Skill | None:
    if not isinstance(item, dict):
        return None
    skill_id = item.get("id") or item.get("skill_id") or item.get("cluster_id")
    if not isinstance(skill_id, str) or not skill_id:
        return None
    derived = item.get("source_case_ids") or item.get("derived_from_case_ids") or []
    if not isinstance(derived, list):
        derived = []
    derived = [str(x) for x in derived if isinstance(x, (str, int))]
    try:
        return Skill(
            id=str(skill_id),
            name=str(item.get("name") or "unnamed skill"),
            description=str(item.get("description") or item.get("content") or ""),
            category=item.get("category"),
            region=item.get("region"),
            derived_from_case_ids=derived,
            created_at=_parse_dt(item.get("timestamp") or item.get("created_at")),
        )
    except Exception:  # noqa: BLE001
        logger.exception("memory_store: skill mapping failed for item=%r", item)
        return None


async def list_cases(user_id: str | None = None) -> list[Case]:
    """Read agent_case entries from EverOS for ``user_id``.

    Returns ``[]`` on missing user_id / key / SDK / network / mapping
    error (logged). Callers MUST pass a real user id — there is no
    demo-user fallback.
    """
    if not user_id:
        logger.info("list_cases: no user_id provided; returning [].")
        return []
    uid = user_id
    client = _get_client()
    if client is None:
        logger.info("list_cases: EverOS client unavailable; returning [].")
        return []

    def _call() -> list[Case]:
        try:
            response = client.v1.memories.get(
                filters={"user_id": uid},
                memory_type="agent_case",
            )
        except Exception:  # noqa: BLE001
            logger.exception("list_cases: EverOS get() failed (non-fatal).")
            return []

        items: list[Any]
        if isinstance(response, dict):
            items = response.get("agent_cases") or response.get("results") or []
        elif isinstance(response, list):
            items = response
        else:
            items = []
        cases: list[Case] = []
        for item in items:
            case = _case_from_dict(item, default_user_id=uid)
            if case is not None:
                cases.append(case)
        return cases

    try:
        return await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception("list_cases: dispatch failed (non-fatal); returning [].")
        return []


async def list_top_cases_for_draft(
    user_id: str | None,
    category: str | None,
    region: str | None,
    limit: int = 5,
) -> list[dict]:
    """Return the top analyzed Cases for a category + region.

    Phase H of the chat-first plan — the negotiator's draft path calls
    this to inject prior-negotiation lessons into the next draft. Each
    returned entry carries the full analyzer JSON payload (``what_worked``,
    ``what_didnt``, ``tactical_lessons``, ``category``, ``region``,
    ``outcome``) rather than the trimmed ``Case`` contract shape — the
    LLM needs the full structured detail.

    Filters:

    - ``user_id`` (required) — tenant scope. Missing user → ``[]``.
    - ``category`` — exact match on the analyzer's ``category`` field.
      Pass an empty string to skip the filter.
    - ``region`` — exact match on the analyzer's ``region`` field. Pass
      an empty string to skip the filter.

    Ordering: most-recent first (by the EverOS ``timestamp``).

    Best-effort: missing EVEROS_API_KEY / SDK / network errors all
    return ``[]`` — the negotiator runs without past-lessons in that
    case.
    """
    if not user_id:
        return []
    client = _get_client()
    if client is None:
        return []

    def _call() -> list[dict]:
        try:
            response = client.v1.memories.get(
                filters={"user_id": user_id},
                memory_type="agent_case",
            )
        except Exception:  # noqa: BLE001
            logger.exception("list_top_cases_for_draft: EverOS get() failed (non-fatal).")
            return []

        items: list[Any]
        if isinstance(response, dict):
            items = response.get("agent_cases") or response.get("results") or []
        elif isinstance(response, list):
            items = response
        else:
            items = []

        wanted_category = (category or "").strip().lower()
        wanted_region = (region or "").strip().lower()

        results: list[tuple[datetime, dict]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            payload = _extract_analyzer_payload(item)
            if payload is None:
                continue
            payload_category = str(payload.get("category") or "").strip().lower()
            payload_region = str(payload.get("region") or "").strip().lower()
            if wanted_category and payload_category and payload_category != wanted_category:
                continue
            if wanted_region and payload_region and payload_region != wanted_region:
                continue
            ts = _parse_dt(item.get("timestamp") or item.get("created_at"))
            results.append((ts, payload))

        results.sort(key=lambda t: t[0], reverse=True)
        capped = results[: max(0, int(limit))]
        return [payload for (_, payload) in capped]

    try:
        return await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception(
            "list_top_cases_for_draft: dispatch failed (non-fatal); returning []."
        )
        return []


async def delete_case(case_id: str) -> bool:
    """Hard-delete a Case from EverOS.

    Phase J — invoked by ``DELETE /api/memory/cases/{case_id}``. Returns
    True when the delete call succeeded, False on missing key / SDK /
    network error. Caller is responsible for cleaning up the local
    ``case_notes`` row.
    """
    if not case_id:
        return False
    client = _get_client()
    if client is None:
        return False

    def _call() -> bool:
        try:
            client.v1.memories.delete(memory_id=case_id)
            return True
        except Exception:  # noqa: BLE001
            logger.exception(
                "delete_case: EverOS delete failed case_id=%s (non-fatal).",
                case_id,
            )
            return False

    try:
        return await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception(
            "delete_case: dispatch failed case_id=%s (non-fatal).", case_id
        )
        return False


async def get_case_detail(
    case_id: str, user_id: str | None
) -> dict | None:
    """Read one Case + its parsed analyzer payload from EverOS.

    Used by the per-Case detail view in the Memory page. Returns a dict
    shaped as:

        ``{case: <Case>.model_dump(), analyzer: <parsed-json>|None,
           raw: <raw-everos-item>}``

    or None when the Case isn't found / EverOS unavailable.
    """
    if not case_id or not user_id:
        return None
    client = _get_client()
    if client is None:
        return None

    def _call() -> dict | None:
        try:
            response = client.v1.memories.get(
                filters={"user_id": user_id},
                memory_type="agent_case",
            )
        except Exception:  # noqa: BLE001
            logger.exception("get_case_detail: EverOS get() failed (non-fatal).")
            return None

        items: list[Any]
        if isinstance(response, dict):
            items = response.get("agent_cases") or response.get("results") or []
        elif isinstance(response, list):
            items = response
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            this_id = item.get("id") or item.get("case_id") or item.get("session_id")
            if str(this_id) == case_id:
                case = _case_from_dict(item, default_user_id=user_id)
                if case is None:
                    continue
                return {
                    "case": case.model_dump(mode="json"),
                    "analyzer": _extract_analyzer_payload(item),
                    "raw": item,
                }
        return None

    try:
        return await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception(
            "get_case_detail: dispatch failed case_id=%s (non-fatal).", case_id
        )
        return None


async def list_skills(user_id: str | None = None) -> list[Skill]:
    """Read agent_skill entries from EverOS.

    Skills aren't strictly user-scoped in the EverOS docs we have, but we
    still pass ``user_id`` as a filter to keep things isolated when
    supported. Callers MUST pass a real user id; missing id yields ``[]``.
    """
    if not user_id:
        logger.info("list_skills: no user_id provided; returning [].")
        return []
    uid = user_id
    client = _get_client()
    if client is None:
        logger.info("list_skills: EverOS client unavailable; returning [].")
        return []

    def _call() -> list[Skill]:
        try:
            response = client.v1.memories.get(
                filters={"user_id": uid},
                memory_type="agent_skill",
            )
        except Exception:  # noqa: BLE001
            logger.exception("list_skills: EverOS get() failed (non-fatal).")
            return []

        items: list[Any]
        if isinstance(response, dict):
            items = response.get("agent_skills") or response.get("results") or []
        elif isinstance(response, list):
            items = response
        else:
            items = []
        skills: list[Skill] = []
        for item in items:
            skill = _skill_from_dict(item)
            if skill is not None:
                skills.append(skill)
        return skills

    try:
        return await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception("list_skills: dispatch failed (non-fatal); returning [].")
        return []


# ---------------------------------------------------------------------------
# Write APIs — full-transcript Case on job close


async def write_case_on_completion(
    job: "JobORM",
    session: "AsyncSession",
) -> None:
    """Write a full-negotiation Case to EverOS + trigger Skill extraction.

    Pulls the message thread from Postgres, maps to EverOS's expected
    message shape (``{role, timestamp, content}``), and calls
    ``client.v1.memories.agent.add``. After the Case write, kicks off a
    background ``_trigger_skill_extraction`` task that calls EverOS's
    ``client.v1.memories.agent.flush(user_id, session_id)`` endpoint —
    flush triggers agent-aware boundary detection which extracts Cases
    and Skills from accumulated trajectory messages (per the SDK docs).

    All failures are logged + swallowed.
    """
    from api.models import MessageThread

    client = _get_client()
    if client is None:
        logger.info("write_case_on_completion: EverOS client unavailable; skipping.")
        return

    try:
        rows = await MessageThread.list_for_job(session, job.id)
    except Exception:  # noqa: BLE001
        logger.exception("write_case_on_completion: DB read failed (non-fatal).")
        return

    def _role_for_everos(role: str) -> str:
        # EverOS expects {user, assistant, system}; map our roles:
        # buyer_agent => assistant (Goti is the assistant negotiating)
        # seller      => user      (the other side's reply)
        # system      => system
        if role == "buyer_agent":
            return "assistant"
        if role == "seller":
            return "user"
        return "system"

    messages = [
        {
            "role": _role_for_everos(r.role),
            "timestamp": int(r.sent_at.timestamp() * 1000) if r.sent_at else int(time.time() * 1000),
            "content": r.text,
        }
        for r in rows
    ]

    if not messages:
        # Nothing to write — log and bail (still graceful).
        logger.info(
            "write_case_on_completion: no messages for job=%s; skipping Case write.", job.id
        )
        return

    session_id = f"goti-job-{job.id}"
    user_id = job.user_id

    def _call() -> None:
        try:
            client.v1.memories.agent.add(
                user_id=user_id,
                session_id=session_id,
                messages=messages,
            )
            logger.info(
                "write_case_on_completion: ok user=%s session=%s msgs=%d",
                user_id,
                session_id,
                len(messages),
            )
        except Exception:  # noqa: BLE001
            logger.exception("write_case_on_completion: EverOS add() failed (non-fatal).")

    try:
        await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception("write_case_on_completion: dispatch failed (non-fatal).")

    # Trigger Skill extraction. Per EverOS SDK 0.4.0 the right primitive
    # is ``client.v1.memories.agent.flush(user_id, session_id)`` —
    # docstring reads "Trigger agent-aware boundary detection on
    # accumulated agent trajectory messages. Extracts agent cases and
    # skills when boundary is detected." We fire-and-forget so the
    # close-path stays fast.
    try:
        asyncio.create_task(_trigger_skill_extraction(user_id, session_id))
    except RuntimeError:
        # No running loop (sync test harness) — degrade silently; tests can
        # invoke ``_trigger_skill_extraction`` directly.
        logger.info(
            "write_case_on_completion: no running asyncio loop — "
            "skill extraction will not be triggered here."
        )


async def _trigger_skill_extraction(user_id: str, session_id: str) -> None:
    """Call EverOS's ``memories.agent.flush`` to extract Skills.

    Per the EverOS SDK 0.4.0 surface (verified by inspecting
    ``everos/resources/v1/memories/agent.py``), ``flush(user_id,
    session_id)`` is the canonical trigger: "Trigger agent-aware
    boundary detection on accumulated agent trajectory messages.
    Extracts agent cases and skills when boundary is detected."

    Fire-and-forget — failures are logged + swallowed so a flaky EverOS
    never blocks job close.
    """
    if not user_id:
        return
    client = _get_client()
    if client is None:
        logger.info(
            "_trigger_skill_extraction: EverOS client unavailable; skipping."
        )
        return

    def _call() -> None:
        try:
            client.v1.memories.agent.flush(
                user_id=user_id, session_id=session_id
            )
            logger.info(
                "_trigger_skill_extraction: flush ok user=%s session=%s",
                user_id,
                session_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "_trigger_skill_extraction: flush failed user=%s session=%s "
                "(non-fatal).",
                user_id,
                session_id,
            )

    try:
        await asyncio.to_thread(_call)
    except Exception:  # noqa: BLE001
        logger.exception(
            "_trigger_skill_extraction: dispatch failed user=%s (non-fatal).",
            user_id,
        )
