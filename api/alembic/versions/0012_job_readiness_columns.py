"""Add ``jobs.ready_to_close`` / ``close_signal_reason`` / ``suggested_close_price``.

Phase E of the ancient-brewing-brooks plan — drives the new classifier
reasoner's verdict surface. The classifier
(``api/agents/classifier.py``) auto-invokes after every new buyer /
seller message and writes its readiness signal to these columns; the UI
surfaces ``ready_to_close=True`` as a "Ready to close" badge on the
deal page that opens the finalize-close modal.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-22 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "ready_to_close",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("close_signal_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("suggested_close_price", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "suggested_close_price")
    op.drop_column("jobs", "close_signal_reason")
    op.drop_column("jobs", "ready_to_close")
