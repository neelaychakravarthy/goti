"""Tests for the Pass-6 Google OAuth ``current_user`` dependency.

We don't talk to Google during tests — instead we stub
``api.auth.verify_google_id_token`` to return a synthetic claims dict.
That exercises:

1. ``current_user`` calls ``User.upsert_from_google(claims)`` and the
   resulting row appears in the DB.
2. Protected endpoints reject with 401 when no Authorization header is
   sent.
3. Protected endpoints accept with a valid (stubbed) bearer token and
   route to the resolved User row.
"""

from __future__ import annotations

import asyncio

import pytest

# Disable Postgres-only alembic migrations during test boot (SQLite path).
import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]

from api.db import Base, engine  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _setup_schema():
    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    yield


@pytest.fixture
def stub_verify(monkeypatch):
    """Replace verify_google_id_token with a deterministic stub.

    The stub maps token "valid-token-X" → claims with sub=user-X /
    email=userX@example.com. Anything else raises HTTPException(401).
    """
    from fastapi import HTTPException, status

    import api.auth as auth_mod

    async def _stub(token: str) -> dict:
        if not isinstance(token, str) or not token.startswith("valid-token-"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="stub: token not valid",
            )
        suffix = token[len("valid-token-") :] or "default"
        return {
            "sub": f"google-sub-{suffix}",
            "email": f"user-{suffix}@example.com",
            "name": f"User {suffix.upper()}",
            "picture": f"https://lh3.googleusercontent.com/{suffix}",
        }

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _stub)
    # Also patch the symbol where it's imported by the dependency closures.
    return _stub


def test_protected_endpoint_rejects_without_token(stub_verify):
    """GET /api/me with no Authorization header returns 401."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        response = c.get("/api/me")
    assert response.status_code == 401, response.text


def test_protected_endpoint_rejects_malformed_token(stub_verify):
    """GET /api/me with a bad Authorization header returns 401."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        response = c.get(
            "/api/me", headers={"Authorization": "NotBearer something"}
        )
    assert response.status_code == 401


def test_current_user_creates_user_row_and_returns_profile(stub_verify):
    """First sign-in for a fresh token upserts a User + returns the profile."""
    from fastapi.testclient import TestClient

    from api.db import AsyncSessionLocal
    from api.models import User

    with TestClient(app) as c:
        response = c.get(
            "/api/me",
            headers={"Authorization": "Bearer valid-token-alpha"},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email"] == "user-alpha@example.com"
    assert data["name"] == "User ALPHA"
    assert data["picture"] == "https://lh3.googleusercontent.com/alpha"
    assert data["onboarding_completed"] is False
    assert isinstance(data.get("integrations"), list)

    async def _check_row():
        async with AsyncSessionLocal() as session:
            return await User.get_by_google_sub(session, "google-sub-alpha")

    user = asyncio.run(_check_row())
    assert user is not None
    assert user.email == "user-alpha@example.com"


def test_repeated_signin_updates_profile_fields(stub_verify, monkeypatch):
    """Second sign-in with changed Google data updates email / name / picture."""
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    import api.auth as auth_mod
    from api.db import AsyncSessionLocal
    from api.models import User

    # Second-call stub: same sub, different fields.
    async def _evolving_stub(token: str) -> dict:
        if token == "valid-token-evolving-v1":
            return {
                "sub": "google-sub-evolving",
                "email": "evo@old.example.com",
                "name": "Old Name",
                "picture": "https://lh3/old",
            }
        if token == "valid-token-evolving-v2":
            return {
                "sub": "google-sub-evolving",
                "email": "evo@new.example.com",
                "name": "New Name",
                "picture": "https://lh3/new",
            }
        raise HTTPException(status_code=401, detail="stub")

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _evolving_stub)

    with TestClient(app) as c:
        r1 = c.get(
            "/api/me",
            headers={"Authorization": "Bearer valid-token-evolving-v1"},
        )
        assert r1.status_code == 200
        r2 = c.get(
            "/api/me",
            headers={"Authorization": "Bearer valid-token-evolving-v2"},
        )
        assert r2.status_code == 200

    async def _check_row():
        async with AsyncSessionLocal() as session:
            return await User.get_by_google_sub(
                session, "google-sub-evolving"
            )

    user = asyncio.run(_check_row())
    assert user is not None
    assert user.email == "evo@new.example.com"
    assert user.name == "New Name"
    assert user.picture == "https://lh3/new"


def test_onboarding_complete_route(stub_verify):
    """POST /api/me/onboarding/complete flips the flag on the User row."""
    from fastapi.testclient import TestClient

    from api.db import AsyncSessionLocal
    from api.models import User

    with TestClient(app) as c:
        # First make sure the user exists.
        r1 = c.get(
            "/api/me",
            headers={"Authorization": "Bearer valid-token-onboarder"},
        )
        assert r1.status_code == 200
        assert r1.json()["onboarding_completed"] is False

        r2 = c.post(
            "/api/me/onboarding/complete",
            headers={"Authorization": "Bearer valid-token-onboarder"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json() == {"ok": True}

    async def _check_row():
        async with AsyncSessionLocal() as session:
            return await User.get_by_google_sub(
                session, "google-sub-onboarder"
            )

    user = asyncio.run(_check_row())
    assert user is not None
    assert user.onboarding_completed is True


def test_update_location_route(stub_verify):
    """PATCH /api/me/location sets the location field."""
    from fastapi.testclient import TestClient

    from api.db import AsyncSessionLocal
    from api.models import User

    with TestClient(app) as c:
        r1 = c.get(
            "/api/me",
            headers={"Authorization": "Bearer valid-token-loc"},
        )
        assert r1.status_code == 200

        r2 = c.patch(
            "/api/me/location",
            headers={"Authorization": "Bearer valid-token-loc"},
            json={"location": "San Francisco"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["ok"] is True
        assert r2.json()["location"] == "San Francisco"

    async def _check_row():
        async with AsyncSessionLocal() as session:
            return await User.get_by_google_sub(
                session, "google-sub-loc"
            )

    user = asyncio.run(_check_row())
    assert user is not None
    assert user.location == "San Francisco"


def test_protected_route_rejects_when_google_client_id_unset(monkeypatch):
    """If GOOGLE_OAUTH_CLIENT_ID is missing, verify raises 500.

    The current_user dep wraps that as 401 since it bubbles through
    verify_google_id_token; we just confirm it doesn't succeed.
    """
    import api.auth as auth_mod
    from api.config import get_settings

    # Stub verify_google_id_token back to a real-shaped check so settings
    # is consulted; bypass the google-auth import.
    async def _check_settings(token: str) -> dict:
        from fastapi import HTTPException

        s = get_settings()
        if not s.google_oauth_client_id:
            raise HTTPException(
                status_code=500,
                detail="GOOGLE_OAUTH_CLIENT_ID not configured",
            )
        # If somehow set, accept any token (irrelevant for this test).
        return {"sub": "x", "email": "x@example.com"}

    monkeypatch.setattr(auth_mod, "verify_google_id_token", _check_settings)
    # Ensure setting is unset for this test.
    monkeypatch.setattr(get_settings(), "google_oauth_client_id", None)

    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        response = c.get(
            "/api/me",
            headers={"Authorization": "Bearer anything"},
        )
    # 500 from settings check is fine — non-200 confirms the dep gated.
    assert response.status_code in (401, 500)
