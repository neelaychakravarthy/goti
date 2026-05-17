"""Add ``async_tasks`` table for durable background-task persistence.

Phase O of the ancient-brewing-brooks followups round. Backs the
in-memory ``_RUNNING_TASKS`` registry in ``api/orchestration/tasks.py``
with a durable row per task so the user can resume work that was
interrupted by a process restart. On startup the lifespan hook flips
every ``running`` row to ``interrupted``; the chat-first UI lists
those via ``GET /api/hunts/{id}/stopped-tasks`` with a Resume button
per row that re-spawns the task via ``POST /api/tasks/{id}/resume``.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-22 14:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent. Same rationale as 0013 — the early ``index=True`` +
    # explicit ``op.create_index`` combo caused duplicate-index errors
    # on partially-applied DBs. Raw SQL with ``IF NOT EXISTS`` recovers.
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS async_tasks (
                id VARCHAR(64) PRIMARY KEY,
                kind VARCHAR(64) NOT NULL,
                label TEXT NOT NULL,
                user_id VARCHAR(255) NOT NULL,
                hunt_id VARCHAR(64),
                job_id VARCHAR(64),
                status VARCHAR(32) NOT NULL DEFAULT 'running',
                summary TEXT,
                started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMP WITH TIME ZONE,
                resume_payload JSONB
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_async_tasks_user_id "
            "ON async_tasks (user_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_async_tasks_hunt_id "
            "ON async_tasks (hunt_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_async_tasks_status "
            "ON async_tasks (status)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_async_tasks_status"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_async_tasks_hunt_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_async_tasks_user_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS async_tasks"))
