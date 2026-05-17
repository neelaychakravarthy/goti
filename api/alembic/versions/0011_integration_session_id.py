"""Add ``integration_accounts.live_view_session_id`` for kept-alive session cleanup.

The link flow mints a Browserbase Live View session with
``keep_alive=True`` so the user can leave the login tab open across
clicks. Without persisting the session id, ``/finish`` had no way to
release the kept-alive session — it leaked until Browserbase's idle
timeout. This column lets ``/finish`` (and ``/unlink``) call
``end_session`` on the exact session minted for that link.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-21 22:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "integration_accounts",
        sa.Column("live_view_session_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_accounts", "live_view_session_id")
