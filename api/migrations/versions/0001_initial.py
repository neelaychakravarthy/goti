"""initial: users, integration_accounts, listings_cache

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-16

Stream C round 1 schema. Stream B adds jobs, message_threads,
approval_queue, goals on its branch — those land in a separate revision.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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

    op.create_table(
        "integration_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("actionbook_profile_id", sa.String(length=128), nullable=True),
        sa.Column(
            "raw_session",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_integration_accounts_user_provider",
        "integration_accounts",
        ["user_id", "provider"],
        unique=True,
    )

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
        # goal_id intentionally has no FK — Stream B owns `goals`. FK added later.
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


def downgrade() -> None:
    op.drop_index("ix_listings_cache_goal_id", table_name="listings_cache")
    op.drop_table("listings_cache")
    op.drop_index(
        "ix_integration_accounts_user_provider",
        table_name="integration_accounts",
    )
    op.drop_table("integration_accounts")
    op.drop_table("users")
