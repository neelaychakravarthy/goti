"""Phase J — Case delete route tests.

Covers:
- ``DELETE /api/memory/cases/{case_id}`` calls EverOS delete + removes
  the local ``case_notes`` row.
- 200 with ``everos_deleted=false`` when the EverOS client is unavailable
  (graceful degrade).
- Tenant isolation: deleting case_id X for user A doesn't remove
  user B's notes row for the same case_id.
"""

from __future__ import annotations

import asyncio
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


def test_delete_route_calls_everos_and_removes_notes(
    client, stub_verify_token, authed_headers
):
    """DELETE removes notes + calls EverOS delete + returns 200."""
    from api import memory_store
    from api.models import CaseNotes, User

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
            uid = str(user.id)
            await CaseNotes.upsert(
                s,
                case_id="case-to-delete",
                user_id=uid,
                notes_text="some text",
            )
            await s.commit()
            return uid

    uid = asyncio.run(_seed())

    delete_calls: list[str] = []

    async def _fake_delete(case_id):
        delete_calls.append(case_id)
        return True

    with patch.object(memory_store, "delete_case", _fake_delete):
        response = client.delete(
            "/api/memory/cases/case-to-delete", headers=authed_headers
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["case_id"] == "case-to-delete"
    assert body["everos_deleted"] is True
    assert body["notes_rows_deleted"] == 1
    assert delete_calls == ["case-to-delete"]

    # And the local notes row is gone.
    async def _verify():
        async with AsyncSessionLocal() as s:
            row = await CaseNotes.get(s, "case-to-delete", uid)
            return row

    assert asyncio.run(_verify()) is None


def test_delete_route_handles_everos_unavailable(
    client, stub_verify_token, authed_headers
):
    """Returns ok=true with everos_deleted=false when EverOS isn't reachable."""
    from api import memory_store

    async def _fake_delete(case_id):
        return False

    with patch.object(memory_store, "delete_case", _fake_delete):
        response = client.delete(
            "/api/memory/cases/case-unreachable",
            headers=authed_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["everos_deleted"] is False


def test_delete_route_only_deletes_current_users_notes(
    client, stub_verify_token, authed_headers
):
    """A delete by user A on a case owned by user B is a no-op for the notes row.

    Case ids are user-scoped in EverOS so two users never share a
    case_id row in case_notes. The DELETE endpoint runs the local
    notes purge with a ``(case_id, user_id)`` WHERE — verify that when
    the only existing notes row belongs to a different user, nothing
    is deleted locally and ``notes_rows_deleted=0``.
    """
    from api import memory_store
    from api.models import CaseNotes, User

    async def _seed():
        async with AsyncSessionLocal() as s:
            # The stub_verify_token user IS NOT user_b.
            user_b = await User.upsert_from_google(
                s,
                {
                    "sub": "case-delete-isolation-user-b",
                    "email": "case-delete-isolation-b@example.com",
                    "name": "Other",
                },
            )
            await CaseNotes.upsert(
                s,
                case_id="case-not-mine",
                user_id=str(user_b.id),
                notes_text="B's note",
            )
            await s.commit()
            return str(user_b.id)

    uid_b = asyncio.run(_seed())

    async def _fake_delete(case_id):
        return True

    with patch.object(memory_store, "delete_case", _fake_delete):
        response = client.delete(
            "/api/memory/cases/case-not-mine", headers=authed_headers
        )
    assert response.status_code == 200
    body = response.json()
    # The test user (stub_verify_token = "test-sub") doesn't own this
    # notes row, so the local delete matched 0 rows.
    assert body["notes_rows_deleted"] == 0

    # B's notes row should still exist.
    async def _verify():
        async with AsyncSessionLocal() as s:
            return await CaseNotes.get(s, "case-not-mine", uid_b)

    b_row = asyncio.run(_verify())
    assert b_row is not None
    assert b_row.notes_text == "B's note"
