"""hunts table + jobs.hunt_id FK

Adds the long-running ``hunts`` lifecycle anchor and extends ``jobs``
with a nullable ``hunt_id`` FK so jobs spawned from the pick-phase of a
hunt can be joined back to their parent.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-16 00:00:02.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------- hunts ----------------
    op.create_table(
        "hunts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("goal_text", sa.Text(), nullable=False),
        sa.Column(
            "brief",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("budget", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'awaiting_clarification'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_hunts_user_id", "hunts", ["user_id"])

    # ---------------- jobs.hunt_id ----------------
    op.add_column(
        "jobs",
        sa.Column(
            "hunt_id",
            UUID(as_uuid=False),
            sa.ForeignKey("hunts.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_jobs_hunt_id", "jobs", ["hunt_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_hunt_id", table_name="jobs")
    op.drop_column("jobs", "hunt_id")
    op.drop_index("ix_hunts_user_id", table_name="hunts")
    op.drop_table("hunts")
