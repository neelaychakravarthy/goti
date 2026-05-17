"""Memory routes — read/edit/delete Cases + Skills from EverOS.

On missing EVEROS_API_KEY / SDK / transport error, the read endpoints
return ``[]`` (per the graceful-degradation requirement in the plan).
Mutations propagate failures up — the frontend surfaces a toast on
4xx/5xx so the user knows EverOS isn't reachable.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api import memory_store as memory_store_module
from api.auth import current_user
from api.contracts import Case, Skill
from api.db import get_session
from api.memory_store import list_cases, list_skills
from api.models import CaseNotes, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


class CaseNotesPayload(BaseModel):
    notes_text: str = ""


@router.get("/cases", response_model=list[Case])
async def get_cases(user: User = Depends(current_user)) -> list[Case]:
    return await list_cases(user_id=str(user.id))


@router.get("/skills", response_model=list[Skill])
async def get_skills(user: User = Depends(current_user)) -> list[Skill]:
    return await list_skills(user_id=str(user.id))


@router.get("/cases/{case_id}")
async def get_one_case(
    case_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Read one Case + its structured analyzer payload + the user's notes.

    Returns ``{case, analyzer, notes_text}`` shape. ``analyzer`` is the
    parsed JSON payload the analyzer reasoner wrote
    (``{what_worked, what_didnt, key_moments, tactical_lessons,
       category, region, confidence, outcome}``); None when the Case is
    legacy (transcript-shaped) or the parse failed.
    """
    uid = str(user.id)
    detail = await memory_store_module.get_case_detail(case_id=case_id, user_id=uid)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown case_id: {case_id}")

    case_dict = detail.get("case") or {}
    if str(case_dict.get("user_id") or "") != uid:
        # EverOS already filtered by user_id; defensive guard for any
        # stray rows.
        raise HTTPException(
            status_code=403, detail="case does not belong to the current user"
        )

    notes_row = await CaseNotes.get(session, case_id, uid)
    notes_text = notes_row.notes_text if notes_row is not None else ""

    return {
        "case": case_dict,
        "analyzer": detail.get("analyzer"),
        "notes_text": notes_text,
    }


@router.patch("/cases/{case_id}/notes")
async def update_case_notes(
    case_id: str,
    body: CaseNotesPayload,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Persist the user's free-form notes for a Case.

    Tenant-scoped via ``current_user``; the notes row is keyed by
    ``(case_id, user_id)``. Idempotent — overwrites on each call.
    """
    uid = str(user.id)
    notes_text = body.notes_text or ""
    row = await CaseNotes.upsert(
        session, case_id=case_id, user_id=uid, notes_text=notes_text
    )
    await session.commit()
    return {
        "ok": True,
        "case_id": row.case_id,
        "notes_text": row.notes_text,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.delete("/cases/{case_id}")
async def delete_case_endpoint(
    case_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Hard-delete a Case from EverOS + drop the local notes row.

    Best-effort on the EverOS side — a missing API key / transport
    failure still returns ``ok: true`` with ``everos_deleted: false`` so
    the user's intent ("I'm done with this Case") isn't lost. The notes
    row is always removed locally.
    """
    uid = str(user.id)

    everos_ok = await memory_store_module.delete_case(case_id)
    notes_deleted = await CaseNotes.delete_for_case(
        session, case_id=case_id, user_id=uid
    )
    await session.commit()

    return {
        "ok": True,
        "case_id": case_id,
        "everos_deleted": bool(everos_ok),
        "notes_rows_deleted": int(notes_deleted),
    }
