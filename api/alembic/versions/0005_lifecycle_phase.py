"""hunts.lifecycle_phase column

Adds a granular ``lifecycle_phase`` column to ``hunts`` so the
lifecycle coroutine can resume from the correct phase after a
container restart (idempotent + resumable from DB state).

The existing ``status`` column stays — it's user-facing copy. The new
``lifecycle_phase`` is internal scheduling state with finer granularity.

Phases:
  - ``clarifying``  — Phase 1, clarifier reasoner paused for budget
  - ``discovering`` — Phase 2, running Bright Data + valuation
  - ``valuing``     — Phase 2 sub-state (per-listing valuation in flight)
  - ``picking``     — Phase 3, picker reasoner paused for picks
  - ``negotiating`` — Phase 4, per-job lifecycles in flight
  - ``closed``      — terminal (success)
  - ``error``       — terminal (lifecycle errored)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-17 01:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Default existing rows to ``clarifying`` — they're either in flight or
    # in a terminal state we already capture via ``status``.
    op.add_column(
        "hunts",
        sa.Column(
            "lifecycle_phase",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'clarifying'"),
        ),
    )
    # Backfill from existing status so resumption picks up where we are.
    op.execute(
        "UPDATE hunts SET lifecycle_phase = CASE "
        "WHEN status = 'awaiting_clarification' THEN 'clarifying' "
        "WHEN status = 'discovering' THEN 'discovering' "
        "WHEN status = 'awaiting_picks' THEN 'picking' "
        "WHEN status = 'negotiating' THEN 'negotiating' "
        "WHEN status = 'closed' THEN 'closed' "
        "WHEN status = 'error' THEN 'error' "
        "ELSE 'clarifying' END"
    )
    op.create_index("ix_hunts_lifecycle_phase", "hunts", ["lifecycle_phase"])


def downgrade() -> None:
    op.drop_index("ix_hunts_lifecycle_phase", table_name="hunts")
    op.drop_column("hunts", "lifecycle_phase")
