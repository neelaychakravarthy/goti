"""EverOS memory-store wrapper.

EverOS SDK is sync; we wrap calls in `asyncio.to_thread()` so they don't
block the FastAPI event loop.

Pass 2 additions: ``list_cases`` and ``list_skills`` (read APIs for the
Memory Bank route) + ``write_case_on_completion`` (writes a full
negotiation transcript to EverOS when a job closes). All graceful-degrade:
on missing key / SDK / network error, the read APIs return ``[]`` and the
write path swallows the error.
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
    """Fire-and-forget: append a 2-message Case to EverOS for the demo user.

    Logs and swallows errors so a missing/broken EverOS never breaks /api/goals.
    """
    settings = get_settings()
    user_id = user_id or settings.demo_user_id
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


def _case_from_dict(item: dict, default_user_id: str) -> Case | None:
    """Defensively map an EverOS agent_case item to a ``Case``.

    Returns None if the item is too malformed to map at all (no id).
    """
    if not isinstance(item, dict):
        return None
    case_id = item.get("id") or item.get("case_id") or item.get("session_id")
    if not isinstance(case_id, str) or not case_id:
        return None

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
    if outcome not in {"closed_deal", "abandoned", "no_response", None}:
        outcome = None

    try:
        return Case(
            id=str(case_id),
            user_id=str(item.get("user_id") or default_user_id),
            title=str(task_intent)[:80] or "untitled case",
            summary=str(approach)[:200],
            outcome=outcome,  # type: ignore[arg-type]
            final_price=final_price,
            category=item.get("category"),
            region=item.get("region"),
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

    Returns ``[]`` on missing key / SDK / network / mapping error (logged).
    """
    settings = get_settings()
    uid = user_id or settings.demo_user_id
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


async def list_skills(user_id: str | None = None) -> list[Skill]:
    """Read agent_skill entries from EverOS.

    Skills aren't strictly user-scoped in the EverOS docs we have, but we
    still pass ``user_id`` as a filter to keep things isolated when
    supported.
    """
    settings = get_settings()
    uid = user_id or settings.demo_user_id
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
    """Write a full-negotiation Case to EverOS.

    Pulls the message thread from Postgres, maps to EverOS's expected
    message shape (``{role, timestamp, content}``), and calls
    ``client.v1.memories.agent.add``. All failures are logged + swallowed.
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
