"""Switch Actionbook integration from OAuth-tokens to Profiles model.

Drops the per-user Clerk-OAuth token columns from ``integration_accounts``
+ the ``actionbook_tool_catalog`` table entirely. Adds
``actionbook_profile_id`` + ``profile_login_url`` to ``integration_accounts``
so each user's link row points at the Actionbook profile provisioned via
``POST /api/profiles``.

Safe wipe: ``DELETE FROM integration_accounts`` runs before the schema
change. No real production users are linked yet — the pre-rewrite OAuth
tokens are unusable under the new Profiles model anyway, so we
intentionally clear them.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-17 02:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safe wipe — pre-rewrite OAuth tokens are unusable under the new
    # Profiles model so we drop the old rows before changing the schema.
    op.execute("DELETE FROM integration_accounts")

    # Drop the OAuth-token columns.
    op.drop_column("integration_accounts", "access_token")
    op.drop_column("integration_accounts", "refresh_token")
    op.drop_column("integration_accounts", "token_expires_at")
    op.drop_column("integration_accounts", "scopes")

    # Add the new Actionbook Profile columns.
    op.add_column(
        "integration_accounts",
        sa.Column(
            "actionbook_profile_id",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "integration_accounts",
        sa.Column("profile_login_url", sa.Text(), nullable=True),
    )

    # Drop the tool catalog table — Profiles don't use the MCP tool surface.
    op.drop_constraint(
        "uq_actionbook_tool_catalog_user_tool",
        "actionbook_tool_catalog",
        type_="unique",
    )
    op.drop_index(
        "ix_actionbook_tool_catalog_tool_name",
        table_name="actionbook_tool_catalog",
    )
    op.drop_index(
        "ix_actionbook_tool_catalog_user_id",
        table_name="actionbook_tool_catalog",
    )
    op.drop_table("actionbook_tool_catalog")

    # Drop the server_default after the column add — future inserts must
    # provide an explicit profile_id (we just emptied the table so this
    # is safe).
    op.alter_column(
        "integration_accounts", "actionbook_profile_id", server_default=None
    )


def downgrade() -> None:
    # Recreate the tool catalog table (mirrors 0006's upgrade).
    op.create_table(
        "actionbook_tool_catalog",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "input_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_actionbook_tool_catalog_user_id",
        "actionbook_tool_catalog",
        ["user_id"],
    )
    op.create_index(
        "ix_actionbook_tool_catalog_tool_name",
        "actionbook_tool_catalog",
        ["tool_name"],
    )
    op.create_unique_constraint(
        "uq_actionbook_tool_catalog_user_tool",
        "actionbook_tool_catalog",
        ["user_id", "tool_name"],
    )

    # Drop the new Profile columns.
    op.drop_column("integration_accounts", "profile_login_url")
    op.drop_column("integration_accounts", "actionbook_profile_id")

    # Restore the OAuth-token columns.
    op.add_column(
        "integration_accounts",
        sa.Column(
            "access_token",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "integration_accounts",
        sa.Column("refresh_token", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_accounts",
        sa.Column(
            "token_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "integration_accounts",
        sa.Column("scopes", sa.String(length=512), nullable=True),
    )
