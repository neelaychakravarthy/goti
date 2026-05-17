"""Rename actionbook_profile_id -> browserbase_context_id.

Drops the column-name baggage from the Actionbook Profiles era + swaps
in Browserbase Context ids. ``profile_login_url`` becomes
``live_view_url`` so the column name reflects the Browserbase concept.

Safe wipe: ``DELETE FROM integration_accounts`` runs before the rename.
No production users carry valid Actionbook profile ids under the new
Browserbase model anyway (private-beta Actionbook Evaluate API wasn't
accessible to us); we drop them rather than leaving orphaned values.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-17 21:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Wipe any partially-onboarded integration data — migration during
    # private beta with no live users carrying valid Actionbook profile
    # ids; safe.
    op.execute("DELETE FROM integration_accounts")
    op.alter_column(
        "integration_accounts",
        "actionbook_profile_id",
        new_column_name="browserbase_context_id",
    )
    op.alter_column(
        "integration_accounts",
        "profile_login_url",
        new_column_name="live_view_url",
    )
    # Drop the vestigial OAuth-era column — never populated under the
    # Browserbase model and not referenced from any code path.
    op.drop_column("integration_accounts", "actionbook_user_id")


def downgrade() -> None:
    op.add_column(
        "integration_accounts",
        sa.Column("actionbook_user_id", sa.String(length=255), nullable=True),
    )
    op.alter_column(
        "integration_accounts",
        "browserbase_context_id",
        new_column_name="actionbook_profile_id",
    )
    op.alter_column(
        "integration_accounts",
        "live_view_url",
        new_column_name="profile_login_url",
    )
