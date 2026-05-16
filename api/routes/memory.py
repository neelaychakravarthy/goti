"""Memory routes — read Cases + Skills from EverOS.

On missing EVEROS_API_KEY / SDK / transport error, returns ``[]`` (per the
graceful-degradation requirement in the plan).
"""

from __future__ import annotations

from fastapi import APIRouter

from api.config import get_settings
from api.contracts import Case, Skill
from api.memory_store import list_cases, list_skills

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/cases", response_model=list[Case])
async def get_cases() -> list[Case]:
    settings = get_settings()
    return await list_cases(user_id=settings.demo_user_id)


@router.get("/skills", response_model=list[Skill])
async def get_skills() -> list[Skill]:
    settings = get_settings()
    return await list_skills(user_id=settings.demo_user_id)
