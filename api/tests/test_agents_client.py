"""Tests for the AgentField reasoner-invocation client.

The key invariant under test: ``_execute_url`` MUST target the
``af_agent_server_url`` (the reasoner process on :8080), NOT the
``af_control_plane_url`` (FastAPI's bridge on :8000). Pointing the
execute URL at the control plane produces a 404 on every reasoner call,
which is exactly the stuck-draft bug that motivated Phase A of the
ancient-brewing-brooks plan.
"""

from __future__ import annotations

import pytest

from api.config import get_settings
from api.orchestration import agents_client


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Drop the lru_cache between tests so env overrides take effect."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_execute_url_uses_agent_server_url(monkeypatch):
    """The reasoner execute URL points at AF_AGENT_SERVER_URL.

    AgentField 0.1.84 registers reasoners at ``POST /reasoners/{name}``
    (see ``agentfield/agent.py:1775``). The earlier guess of
    ``/api/v1/execute/{node}.{method}`` 404s on every call.
    """
    monkeypatch.setenv("AF_AGENT_SERVER_URL", "http://agent.example.com:8080")
    monkeypatch.setenv("AF_CONTROL_PLANE_URL", "http://fastapi.example.com:8000")
    get_settings.cache_clear()
    url = agents_client._execute_url("draft_message")
    assert url == "http://agent.example.com:8080/reasoners/draft_message"
    # Sanity: NOT the control plane URL.
    assert "fastapi.example.com" not in url


def test_execute_url_default_is_agent_server_8080(monkeypatch):
    """Default config (no env override) targets localhost:8080."""
    monkeypatch.delenv("AF_AGENT_SERVER_URL", raising=False)
    monkeypatch.delenv("AF_CONTROL_PLANE_URL", raising=False)
    get_settings.cache_clear()
    url = agents_client._execute_url("assess_listing")
    assert url == "http://localhost:8080/reasoners/assess_listing"


def test_execute_url_strips_trailing_slash(monkeypatch):
    """Trailing slashes on the env var don't double up in the rendered URL."""
    monkeypatch.setenv("AF_AGENT_SERVER_URL", "http://localhost:8080/")
    get_settings.cache_clear()
    url = agents_client._execute_url("pick_listings")
    assert url == "http://localhost:8080/reasoners/pick_listings"
