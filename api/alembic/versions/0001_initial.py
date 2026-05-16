"""initial — converged schema (Stream B + C tables in one revision)

Tables created (in dependency order):
  - users               (Stream C)
  - integration_accounts (Stream B OAuth-token shape)
  - listings_cache      (Stream C)
  - jobs                (Stream B)
  - message_threads     (Stream B, FK -> jobs)
  - approval_queue      (Stream B, FK -> jobs)

Revision ID: 0001
Revises:
Create Date: 2026-05-16 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------- users (Stream C) ----------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # ---------------- integration_accounts (Stream B OAuth shape) ----------------
    # user_id is intentionally a free VARCHAR(255), not a FK to users.id —
    # see api/models.py docstring for the type-divergence note.
    op.create_table(
        "integration_accounts",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("actionbook_user_id", sa.String(length=255), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.String(length=512), nullable=True),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_integration_user_provider"
        ),
    )
    op.create_index(
        "ix_integration_accounts_user_id",
        "integration_accounts",
        ["user_id"],
    )
    op.create_index(
        "idx_integration_user_provider_status",
        "integration_accounts",
        ["user_id", "provider", "status"],
    )

    # ---------------- listings_cache (Stream C) ----------------
    op.create_table(
        "listings_cache",
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("listing_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_cents", sa.BigInteger(), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=8),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "raw_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        # goal_id intentionally has no FK — `goals` table not yet present.
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("marketplace", "listing_id", name="pk_listings_cache"),
    )
    op.create_index(
        "ix_listings_cache_goal_id",
        "listings_cache",
        ["goal_id"],
    )

    # ---------------- jobs (Stream B) ----------------
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

    # ---------------- message_threads (Stream B) ----------------
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

    # ---------------- approval_queue (Stream B) ----------------
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
    op.drop_index("ix_listings_cache_goal_id", table_name="listings_cache")
    op.drop_table("listings_cache")
    op.drop_index(
        "idx_integration_user_provider_status",
        table_name="integration_accounts",
    )
    op.drop_index(
        "ix_integration_accounts_user_id",
        table_name="integration_accounts",
    )
    op.drop_table("integration_accounts")
    op.drop_table("users")
