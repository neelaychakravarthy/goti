"""Add ``hunt_activity_events`` table — per-step reasoning timeline.

Each row captures one step of the ``browser-use`` Agent loop: the
model's ``thinking`` text, the ``next_goal`` it set, and a short
``action_summary``. Rendered as a live timeline in the hunt detail
view so the user can watch the agent reason through discovery and
negotiation steps in real time.

Hunt-scoped (always carries ``hunt_id``); ``job_id`` is set when the
step happened inside a per-job action (send / fetch) and null for
hunt-level steps (discovery search).

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-21 21:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hunt_activity_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hunt_id",
            UUID(as_uuid=True),
            sa.ForeignKey("hunts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("step_idx", sa.Integer(), nullable=False),
        sa.Column("thinking", sa.Text(), nullable=True),
        sa.Column("next_goal", sa.Text(), nullable=True),
        sa.Column("action_summary", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_hunt_activity_events_hunt_created",
        "hunt_activity_events",
        ["hunt_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hunt_activity_events_hunt_created",
        table_name="hunt_activity_events",
    )
    op.drop_table("hunt_activity_events")
