"""actionbook_tool_catalog table

Persistent catalog of Actionbook MCP tools discovered after the first
successful OAuth. Lets the FB/Nextdoor drivers look up correct tool
names by intent instead of guessing ``f"{marketplace}_send_message"``.

Schema:
  - ``id UUID PK``
  - ``user_id UUID NULL`` (NULL = global; or per-user if Actionbook
    surfaces user-scoped tools)
  - ``tool_name VARCHAR(255)`` (canonical name from tools/list)
  - ``description TEXT NULL``
  - ``input_schema JSONB`` (the tool's params schema)
  - ``discovered_at TIMESTAMPTZ`` (defaults to now())

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-17 01:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "actionbook_tool_catalog",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, nullable=False),
        # user_id stored as VARCHAR(255) for the same reason
        # integration_accounts.user_id is — we write str(User.id) into it
        # and skip the hard FK so the two tables can converge later.
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
    # One row per (user_id, tool_name); NULL user_id participates as
    # the global scope and is unique on its own row.
    op.create_unique_constraint(
        "uq_actionbook_tool_catalog_user_tool",
        "actionbook_tool_catalog",
        ["user_id", "tool_name"],
    )


def downgrade() -> None:
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
