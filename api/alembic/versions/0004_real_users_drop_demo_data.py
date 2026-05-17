"""real users + drop demo data

Replaces the single-demo-user model with a real multi-tenant ``users``
table backed by Google OAuth sign-in.

Schema changes to ``users``:
  - ``google_sub VARCHAR(64) UNIQUE NOT NULL`` (Google subject id)
  - ``name VARCHAR(255) NULL``
  - ``picture VARCHAR(512) NULL`` (Google profile picture URL)
  - ``location VARCHAR(255) NULL`` (user-supplied default location)
  - ``onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE``
  - ``updated_at TIMESTAMPTZ NOT NULL DEFAULT now()``

Demo-data wipe: all rows are dropped from child-and-parent tables in
dependency order. The previous single-tenant hardcoded id will no
longer match anything; new users sign in via Google to repopulate.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------- Wipe demo data (children first, parents last) ----------------
    # FKs cascade where they were declared with ON DELETE CASCADE
    # (message_threads.job_id, approval_queue.job_id). The other rows
    # we wipe explicitly so the post-Pass-6 DB has no orphan state.
    op.execute("DELETE FROM notifications")
    op.execute("DELETE FROM message_threads")
    op.execute("DELETE FROM approval_queue")
    op.execute("DELETE FROM jobs")
    op.execute("DELETE FROM hunts")
    op.execute("DELETE FROM listings_cache")
    op.execute("DELETE FROM integration_accounts")
    op.execute("DELETE FROM users")

    # ---------------- Extend users ----------------
    # google_sub: NOT NULL, but no rows remain after the wipe so we can
    # add the column directly without a backfill sentinel.
    op.add_column(
        "users",
        sa.Column("google_sub", sa.String(length=64), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("picture", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("location", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # google_sub UNIQUE + index
    op.create_unique_constraint(
        "uq_users_google_sub", "users", ["google_sub"]
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"])
    op.create_index("ix_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_constraint("uq_users_google_sub", "users", type_="unique")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "onboarding_completed")
    op.drop_column("users", "location")
    op.drop_column("users", "picture")
    op.drop_column("users", "name")
    op.drop_column("users", "google_sub")
