"""Add ``jobs.final_price`` column for user-confirmed close-deal price.

Replaces the heuristic close-detection path
(``_is_deal_closed`` / ``_extract_agreed_price`` in
``api/orchestration/jobs.py``) — those functions were deleted in the
same pass. Job close now flows exclusively through the user's
``"close_deal"`` approval decision, which writes ``final_price`` to
this column.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-18 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("final_price", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "final_price")
