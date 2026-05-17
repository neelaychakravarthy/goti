"""Add ``case_notes`` table for per-Case custom user notes.

Phase I of the ancient-brewing-brooks chat-first plan. Adds a small
table keyed by ``case_id`` (the EverOS Case id) carrying the user's
free-form notes for that Case. Cases themselves live in EverOS; this
table only stores the user-added annotations so Memory's per-Case
detail view can render an editable notes textarea.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-22 11:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent upgrade — earlier revisions of this migration had a
    # duplicate-index bug (``index=True`` on the column AND an explicit
    # ``op.create_index``) which left a few dev DBs with the table /
    # index already created but the alembic version pointer still at
    # 0012. Raw SQL with ``IF NOT EXISTS`` recovers cleanly from either
    # state — fresh DB or partially-applied.
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS case_notes (
                case_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                notes_text TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_case_notes_user_id "
            "ON case_notes (user_id)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_case_notes_user_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS case_notes"))
