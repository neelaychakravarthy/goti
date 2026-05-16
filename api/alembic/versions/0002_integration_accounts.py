"""0002_integration_accounts — Actionbook OAuth token storage.

Adds the ``integration_accounts`` table that holds per-user, per-provider
OAuth tokens for the Actionbook MCP+Clerk handshake. Chains off the
Stream B initial migration (0001).

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16 15:00:00.000000
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_accounts",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            default=lambda: str(uuid.uuid4()),
        ),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "actionbook_user_id", sa.String(length=255), nullable=True
        ),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column(
            "token_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
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


def downgrade() -> None:
    op.drop_index(
        "idx_integration_user_provider_status",
        table_name="integration_accounts",
    )
    op.drop_index(
        "ix_integration_accounts_user_id", table_name="integration_accounts"
    )
    op.drop_table("integration_accounts")
