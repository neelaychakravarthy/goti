"""Pytest fixtures shared across api/tests.

Round-1 scope: enable mock dispatch by default, and let live tests opt in
via the `live` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `api.*` importable when pytest is run from the api/ dir.
_API_DIR = Path(__file__).resolve().parent.parent  # .../api
_REPO_ROOT = _API_DIR.parent
for p in (str(_REPO_ROOT), str(_API_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def use_mocks(monkeypatch):
    """Force `settings.use_mocks=True` for the duration of a test."""
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "use_mocks", True)
    return True


@pytest.fixture
def no_mocks(monkeypatch):
    """Force `settings.use_mocks=False` (real-path dispatch)."""
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "use_mocks", False)
    return False
