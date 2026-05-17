"""Inbox routes — aggregate cross-hunt items needing the user's attention.

Phase M of the ancient-brewing-brooks chat-first plan. Powers the
sidebar Inbox panel that lists, across every hunt:

- Pending ``ApprovalQueueItem`` rows for the user (approvals awaiting
  decision — outbound message approvals, clarifying questions, etc.).
- Jobs flagged ``ready_to_close=True`` for the user.

Each entry carries enough metadata for the frontend to navigate
directly to the right hunt + tab.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import current_user
from api.db import get_session
from api.models import ApprovalQueueItem, Hunt, Job, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


@router.get("")
async def get_inbox(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the user's cross-hunt Inbox payload.

    Response shape:

    ``{
        items: [
          {
            kind: "approval" | "ready_to_close",
            hunt_id: str | None,
            hunt_title: str | None,
            job_id: str | None,
            approval_request_id: str | None,
            label: str,
            target_href: str,
            created_at: str | None
          },
          ...
        ],
        total: int
      }``

    Items are ordered newest-first. ``total`` is the number of items —
    used by the sidebar to render the badge count.
    """
    uid = str(user.id)

    items: list[dict] = []

    # ---- Pending approvals — surface every undecided queue row for
    # this user. We join via Job → user_id (job-bound rows) AND look up
    # hunt-scoped rows by the ``hunt-<id>-*`` approval_request_id prefix
    # for rows owned by hunts in our tenant.
    hunt_rows_q = await session.execute(
        select(Hunt).where(Hunt.user_id == uid)
    )
    hunts_by_id: dict[str, Hunt] = {h.id: h for h in hunt_rows_q.scalars().all()}

    if hunts_by_id:
        # Job-bound undecided approvals.
        job_q = await session.execute(
            select(Job).where(Job.user_id == uid)
        )
        jobs_by_id: dict[str, Job] = {j.id: j for j in job_q.scalars().all()}

        if jobs_by_id:
            approvals_q = await session.execute(
                select(ApprovalQueueItem).where(
                    ApprovalQueueItem.job_id.in_(jobs_by_id.keys()),
                    ApprovalQueueItem.decision.is_(None),
                )
            )
            for row in approvals_q.scalars().all():
                job = jobs_by_id.get(row.job_id) if row.job_id else None
                hunt_id = job.hunt_id if job else None
                hunt = hunts_by_id.get(hunt_id) if hunt_id else None
                label = _approval_label(row, hunt)
                target_href = _approval_href(row, hunt_id=hunt_id)
                items.append(
                    {
                        "kind": "approval",
                        "hunt_id": hunt_id,
                        "hunt_title": _hunt_title(hunt),
                        "job_id": row.job_id,
                        "approval_request_id": row.approval_request_id,
                        "label": label,
                        "target_href": target_href,
                        "created_at": row.created_at.isoformat()
                        if row.created_at
                        else None,
                    }
                )

        # Hunt-scoped undecided approvals (clarifier / picker / discovery
        # clarifications — approval_request_id starts with ``hunt-<id>-``).
        for hunt_id, hunt in hunts_by_id.items():
            prefix = f"hunt-{hunt_id}-"
            hunt_scoped = await session.execute(
                select(ApprovalQueueItem).where(
                    ApprovalQueueItem.approval_request_id.like(f"{prefix}%"),
                    ApprovalQueueItem.decision.is_(None),
                )
            )
            for row in hunt_scoped.scalars().all():
                # Job-bound rows already handled above; skip duplicates.
                if row.job_id is not None:
                    continue
                items.append(
                    {
                        "kind": "approval",
                        "hunt_id": hunt_id,
                        "hunt_title": _hunt_title(hunt),
                        "job_id": None,
                        "approval_request_id": row.approval_request_id,
                        "label": _approval_label(row, hunt),
                        "target_href": f"/c/{hunt_id}",
                        "created_at": row.created_at.isoformat()
                        if row.created_at
                        else None,
                    }
                )

    # ---- Jobs flagged ready_to_close ----
    ready_q = await session.execute(
        select(Job).where(
            Job.user_id == uid,
            Job.ready_to_close == True,  # noqa: E712 — SA needs == True
            Job.status.notin_(("closed", "cancelled")),
        )
    )
    for job in ready_q.scalars().all():
        hunt = hunts_by_id.get(job.hunt_id) if job.hunt_id else None
        items.append(
            {
                "kind": "ready_to_close",
                "hunt_id": job.hunt_id,
                "hunt_title": _hunt_title(hunt),
                "job_id": job.id,
                "approval_request_id": None,
                "label": (
                    f"{_hunt_title(hunt) or 'Negotiation'}: ready to close"
                    f"{' at $' + str(int(job.suggested_close_price)) if job.suggested_close_price else ''}"
                ),
                "target_href": (
                    f"/c/{job.hunt_id}?deal={job.id}"
                    if job.hunt_id
                    else f"/deal/{job.id}"
                ),
                "created_at": job.last_message_at.isoformat()
                if job.last_message_at
                else (job.created_at.isoformat() if job.created_at else None),
            }
        )

    # Sort newest-first by created_at.
    def _sort_key(it: dict) -> str:
        return it.get("created_at") or ""

    items.sort(key=_sort_key, reverse=True)

    return {"items": items, "total": len(items)}


def _hunt_title(hunt: Hunt | None) -> str | None:
    if hunt is None:
        return None
    title = (hunt.goal_text or "").strip()
    if len(title) > 60:
        title = title[:57] + "…"
    return title or None


def _approval_label(row: ApprovalQueueItem, hunt: Hunt | None) -> str:
    """Build a human-readable label for an approval item."""
    hunt_title = _hunt_title(hunt)
    payload = row.request_payload or {}
    kind = str(payload.get("kind") or "").strip()
    base = "Needs your approval"
    if kind == "clarifying_question":
        base = "Needs an answer"
    elif kind == "approval_needed":
        base = "Needs your approval on a draft message"
    elif "clarify_type" in payload:
        base = "Needs a quick clarification"
    if hunt_title:
        return f"{hunt_title}: {base}"
    return base


def _approval_href(
    row: ApprovalQueueItem, *, hunt_id: str | None
) -> str:
    if hunt_id and row.job_id:
        return (
            f"/c/{hunt_id}?deal={row.job_id}"
            f"&tab=negotiation-{row.job_id}"
        )
    if hunt_id:
        return f"/c/{hunt_id}"
    if row.job_id:
        return f"/deal/{row.job_id}"
    return "/"
