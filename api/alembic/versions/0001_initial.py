"""initial — jobs, message_threads, approval_queue (Stream B owned tables)

Revision ID: 0001
Revises:
Create Date: 2026-05-16 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("listing_id", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("target_price", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_listing_id", "jobs", ["listing_id"])

    op.create_table(
        "message_threads",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_message_threads_job_id", "message_threads", ["job_id"])

    op.create_table(
        "approval_queue",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("draft_reasoning", sa.Text(), nullable=True),
        sa.Column("decision", sa.String(32), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_approval_queue_job_id", "approval_queue", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_approval_queue_job_id", table_name="approval_queue")
    op.drop_table("approval_queue")
    op.drop_index("ix_message_threads_job_id", table_name="message_threads")
    op.drop_table("message_threads")
    op.drop_index("ix_jobs_listing_id", table_name="jobs")
    op.drop_index("ix_jobs_user_id", table_name="jobs")
    op.drop_table("jobs")
