"""Mocked-externals seam for Stream B's local end-to-end testing.

Stream C will reconcile these at convergence — they own the canonical
`api/mocks/discovery.py` and `api/mocks/actionbook.py` content per the
SPEC.md B<->C contract. For now Stream B writes these so the agent
topology + DB-backed routes (Pass 2) can run end-to-end without real
Bright Data / Actionbook API calls.

Flip ``GOTI_USE_MOCKS=1`` in `.env` to swap real integrations for these.
"""

from __future__ import annotations

from api.config import get_settings


def use_mocks() -> bool:
    """Return True iff the mocked-externals gate is enabled (settings.use_mocks)."""
    return get_settings().use_mocks
