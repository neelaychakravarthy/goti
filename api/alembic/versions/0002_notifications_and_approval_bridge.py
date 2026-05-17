"""notifications + ApprovalQueueItem bridge columns

Creates ``notifications`` table for the SSE notification stream and
extends ``approval_queue`` with AgentField control-plane bridge columns
so a single row can drive the full pause/resume lifecycle.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16 00:00:01.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------- approval_queue: bridge columns ----------------
    # `approval_queue.job_id` was previously NOT NULL — pause-only rows
    # (where the agent hasn't been spawned by a Job-bound flow) need a
    # nullable job_id. Drop NOT NULL + drop draft_text NOT NULL so the
    # bridge can upsert with only the AF fields.
    op.alter_column(
        "approval_queue",
        "job_id",
        existing_type=UUID(as_uuid=False),
        nullable=True,
    )
    op.alter_column(
        "approval_queue",
        "draft_text",
        existing_type=sa.Text(),
        nullable=False,
        server_default=sa.text("''"),
    )
    op.add_column(
        "approval_queue",
        sa.Column("execution_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "approval_queue",
        sa.Column("agent_node_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "approval_queue",
        sa.Column("agent_callback_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "approval_queue",
        sa.Column("approval_request_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "approval_queue",
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "approval_queue",
        sa.Column(
            "feedback",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_approval_queue_approval_request_id",
        "approval_queue",
        ["approval_request_id"],
    )
    op.create_index(
        "ix_approval_queue_approval_request_id",
        "approval_queue",
        ["approval_request_id"],
    )

    # ---------------- notifications ----------------
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("hunt_id", UUID(as_uuid=False), nullable=True),
        sa.Column("job_id", UUID(as_uuid=False), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column(
            "body",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "target_href",
            sa.String(length=512),
            nullable=False,
            server_default=sa.text("'/'"),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'unread'"),
        ),
        sa.Column(
            "approval_request_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_hunt_id", "notifications", ["hunt_id"])
    op.create_index(
        "ix_notifications_approval_request_id",
        "notifications",
        ["approval_request_id"],
    )
    op.create_index(
        "ix_notifications_user_status_created",
        "notifications",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_status_created", table_name="notifications")
    op.drop_index("ix_notifications_approval_request_id", table_name="notifications")
    op.drop_index("ix_notifications_hunt_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(
        "ix_approval_queue_approval_request_id",
        table_name="approval_queue",
    )
    op.drop_constraint(
        "uq_approval_queue_approval_request_id",
        "approval_queue",
        type_="unique",
    )
    op.drop_column("approval_queue", "feedback")
    op.drop_column("approval_queue", "request_payload")
    op.drop_column("approval_queue", "approval_request_id")
    op.drop_column("approval_queue", "agent_callback_url")
    op.drop_column("approval_queue", "agent_node_id")
    op.drop_column("approval_queue", "execution_id")
    op.alter_column(
        "approval_queue",
        "draft_text",
        existing_type=sa.Text(),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "approval_queue",
        "job_id",
        existing_type=UUID(as_uuid=False),
        nullable=False,
    )
