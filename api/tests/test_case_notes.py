"""Phase I — per-Case custom notes tests.

Covers:
- Migration 0013 chains off 0012.
- ``CaseNotes`` ORM exposes ``get`` + ``upsert``.
- ``PATCH /api/memory/cases/{case_id}/notes`` upserts notes + 200s.
- ``GET /api/memory/cases/{case_id}`` returns the structured analyzer
  payload + the user's notes joined in.
- Tenant isolation: user A's notes are invisible to user B.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

# Disable Postgres-only alembic migrations during test boot.
import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]

from api.db import AsyncSessionLocal, Base, engine  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _setup_schema():
    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def test_alembic_0013_chains_off_0012():
    from pathlib import Path
    import re

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0013_case_notes.py"
    )
    text = path.read_text()
    rev = re.search(r'revision\s*:\s*str\s*=\s*"([^"]+)"', text)
    down = re.search(
        r'down_revision\s*:\s*Union\[str,\s*None\]\s*=\s*"([^"]+)"', text
    )
    assert rev is not None and rev.group(1) == "0013"
    assert down is not None and down.group(1) == "0012"


def test_case_notes_orm_upsert_and_get():
    """``CaseNotes.upsert`` then ``CaseNotes.get`` round-trips the row."""
    from api.models import CaseNotes

    async def _scenario():
        async with AsyncSessionLocal() as s:
            row = await CaseNotes.upsert(
                s,
                case_id="case-1",
                user_id="user-A",
                notes_text="this seller drove a hard bargain",
            )
            await s.commit()
            fetched = await CaseNotes.get(s, "case-1", "user-A")
            return row, fetched

    row, fetched = asyncio.run(_scenario())
    assert row.case_id == "case-1"
    assert row.notes_text == "this seller drove a hard bargain"
    assert fetched is not None
    assert fetched.notes_text == row.notes_text


def test_case_notes_upsert_updates_existing_row():
    from api.models import CaseNotes

    async def _scenario():
        async with AsyncSessionLocal() as s:
            await CaseNotes.upsert(
                s,
                case_id="case-2",
                user_id="user-B",
                notes_text="first note",
            )
            await s.commit()
            await CaseNotes.upsert(
                s,
                case_id="case-2",
                user_id="user-B",
                notes_text="updated note",
            )
            await s.commit()
            fetched = await CaseNotes.get(s, "case-2", "user-B")
            return fetched

    row = asyncio.run(_scenario())
    assert row is not None
    assert row.notes_text == "updated note"


def test_case_notes_tenant_isolation():
    """``CaseNotes.get`` returns None when queried with the wrong user_id.

    Cases are user-scoped in EverOS so each ``case_id`` only ever has
    one owner — the PK is just ``case_id``. The tenant guard lives in
    the WHERE clause: ``get(case_id, user_id)`` only matches when the
    user_id matches.
    """
    from api.models import CaseNotes

    async def _scenario():
        async with AsyncSessionLocal() as s:
            await CaseNotes.upsert(
                s,
                case_id="case-tenant-1",
                user_id="user-A",
                notes_text="A's private note",
            )
            await s.commit()
            owner_row = await CaseNotes.get(s, "case-tenant-1", "user-A")
            stranger_row = await CaseNotes.get(s, "case-tenant-1", "user-B")
            return owner_row, stranger_row

    owner_row, stranger_row = asyncio.run(_scenario())
    assert owner_row is not None
    assert owner_row.notes_text == "A's private note"
    assert stranger_row is None, (
        "user-B should not see user-A's notes for the same case_id"
    )


def test_patch_case_notes_route_upserts_and_returns_200(
    client, stub_verify_token, authed_headers
):
    """PATCH /api/memory/cases/{id}/notes upserts the row."""
    response = client.patch(
        "/api/memory/cases/case-route-1/notes",
        json={"notes_text": "remember to anchor low"},
        headers=authed_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["case_id"] == "case-route-1"
    assert body["notes_text"] == "remember to anchor low"

    # Second call updates.
    response = client.patch(
        "/api/memory/cases/case-route-1/notes",
        json={"notes_text": "updated text"},
        headers=authed_headers,
    )
    assert response.status_code == 200
    assert response.json()["notes_text"] == "updated text"


def test_get_case_route_returns_analyzer_and_notes(
    client, stub_verify_token, authed_headers
):
    """GET /api/memory/cases/{id} surfaces analyzer JSON + user notes joined in."""
    from api import memory_store
    from api.models import User

    analysis = {
        "what_worked": ["Anchored low"],
        "what_didnt": ["Took too long to counter"],
        "key_moments": [{"turn_idx": 2, "observation": "Seller blinked"}],
        "tactical_lessons": ["Open with leverage"],
        "category": "standing desk",
        "region": "Berkeley",
        "confidence": 0.8,
        "outcome": "closed_deal",
    }

    # Seed a notes row scoped to the test user.
    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "test-sub",
                    "email": "test@example.com",
                    "name": "Test",
                },
            )
            from api.models import CaseNotes

            await CaseNotes.upsert(
                s,
                case_id="case-detail-1",
                user_id=str(user.id),
                notes_text="custom notes here",
            )
            await s.commit()
            return str(user.id)

    uid = asyncio.run(_seed())

    async def _fake_detail(*, case_id, user_id):
        assert case_id == "case-detail-1"
        return {
            "case": {
                "id": case_id,
                "user_id": user_id,
                "title": "Desk negotiation",
                "summary": "Anchored low",
                "outcome": "closed_deal",
                "final_price": 220.0,
                "category": "standing desk",
                "region": "Berkeley",
                "created_at": "2026-05-22T10:00:00Z",
            },
            "analyzer": analysis,
            "raw": {"id": case_id, "content": json.dumps(analysis)},
        }

    with patch.object(memory_store, "get_case_detail", _fake_detail):
        response = client.get(
            "/api/memory/cases/case-detail-1", headers=authed_headers
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["case"]["id"] == "case-detail-1"
    assert body["case"]["user_id"] == uid
    assert body["analyzer"] == analysis
    assert body["notes_text"] == "custom notes here"


def test_get_case_route_404_when_missing(
    client, stub_verify_token, authed_headers
):
    from api import memory_store

    async def _none(*, case_id, user_id):
        return None

    with patch.object(memory_store, "get_case_detail", _none):
        response = client.get(
            "/api/memory/cases/missing-case", headers=authed_headers
        )
    assert response.status_code == 404
