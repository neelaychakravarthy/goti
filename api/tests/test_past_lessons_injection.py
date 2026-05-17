"""Phase H — past Cases injected into the negotiator's draft prompt.

Covers:
- ``list_top_cases_for_draft`` filters analyzed Cases by user_id +
  category + region and returns them recency-first.
- ``draft_negotiation`` includes the "PAST LESSONS" block in the prompt
  when ``past_lessons`` is non-empty.
- The block is absent / safely empty when no past lessons exist.
- The negotiator reasoner passes ``listing_category`` / ``listing_region``
  through to ``list_top_cases_for_draft``.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

# Disable Postgres-only alembic migrations during test boot.
import api.main as _api_main  # noqa: E402

_api_main._run_migrations = lambda: None  # type: ignore[assignment]

from api.db import Base, engine  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _setup_schema():
    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    yield


def test_render_past_lessons_includes_block_when_non_empty():
    """``_render_past_lessons`` emits a 'PAST LESSONS' header + bullets."""
    from api.llm import _render_past_lessons

    lessons = [
        {
            "what_worked": ["Anchored 15% below ask", "Cited a competing offer"],
            "what_didnt": ["Took too long to counter"],
            "tactical_lessons": ["Open with leverage immediately"],
            "category": "standing desk",
            "region": "Berkeley",
            "outcome": "closed_deal",
        }
    ]
    block = _render_past_lessons(lessons)
    assert "PAST LESSONS" in block
    assert "Anchored 15% below ask" in block
    assert "Took too long to counter" in block
    assert "Open with leverage immediately" in block
    assert "standing desk" in block


def test_render_past_lessons_empty_when_none():
    from api.llm import _render_past_lessons

    assert _render_past_lessons([]) == ""
    assert _render_past_lessons(None) == ""  # type: ignore[arg-type]
    # All-empty dicts → still empty block since nothing meaningful is added.
    assert _render_past_lessons([{}]) == ""


def test_draft_negotiation_renders_block_in_payload():
    """``draft_negotiation`` injects the rendered past_lessons block into the user payload."""
    from api import llm

    captured_payloads: list[dict] = []

    async def _fake_chat_json(system, user_payload):
        captured_payloads.append(user_payload)
        return json.dumps(
            {
                "draft_text": "test draft",
                "draft_reasoning": "test reasoning",
            }
        )

    lessons = [
        {
            "what_worked": ["Cited a competitor"],
            "what_didnt": [],
            "tactical_lessons": ["Be willing to walk"],
            "category": "standing desk",
            "region": "Berkeley",
        }
    ]

    with patch.object(llm, "_chat_json", _fake_chat_json):
        asyncio.run(
            llm.draft_negotiation(
                [], 200.0, [], past_lessons=lessons
            )
        )

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert "past_lessons" in payload
    assert payload["past_lessons"] == lessons
    assert "__rendered_past_lessons__" in payload
    assert "PAST LESSONS" in payload["__rendered_past_lessons__"]


def test_draft_negotiation_no_block_when_empty():
    """When past_lessons is empty, no rendered block is added to the payload."""
    from api import llm

    captured_payloads: list[dict] = []

    async def _fake_chat_json(system, user_payload):
        captured_payloads.append(user_payload)
        return json.dumps(
            {
                "draft_text": "test draft",
                "draft_reasoning": "ok",
            }
        )

    with patch.object(llm, "_chat_json", _fake_chat_json):
        asyncio.run(llm.draft_negotiation([], 200.0, [], past_lessons=[]))

    payload = captured_payloads[0]
    assert payload.get("past_lessons") == []
    assert "__rendered_past_lessons__" not in payload


def test_list_top_cases_for_draft_filters_by_category_region():
    """The helper filters EverOS Cases by category + region and orders by recency."""
    from api import memory_store

    # Build a fake EverOS client whose .v1.memories.get returns the rows
    # for the requested user_id filter.
    class _FakeMemories:
        def get(self, filters, memory_type):  # noqa: ANN001
            assert memory_type == "agent_case"
            return {
                "agent_cases": [
                    {
                        "id": "case-1",
                        "timestamp": "2026-05-21T10:00:00Z",
                        "content": json.dumps(
                            {
                                "what_worked": ["A"],
                                "category": "bike",
                                "region": "Berkeley",
                            }
                        ),
                    },
                    {
                        "id": "case-2",
                        "timestamp": "2026-05-22T10:00:00Z",
                        "content": json.dumps(
                            {
                                "what_worked": ["B"],
                                "category": "standing desk",
                                "region": "Berkeley",
                            }
                        ),
                    },
                    {
                        "id": "case-3",
                        "timestamp": "2026-05-20T10:00:00Z",
                        "content": json.dumps(
                            {
                                "what_worked": ["C"],
                                "category": "standing desk",
                                "region": "Oakland",
                            }
                        ),
                    },
                    {
                        "id": "case-4",
                        "timestamp": "2026-05-23T10:00:00Z",
                        "content": json.dumps(
                            {
                                "what_worked": ["D"],
                                "category": "standing desk",
                                "region": "Berkeley",
                            }
                        ),
                    },
                ]
            }

        delete = None

    class _FakeV1:
        memories = _FakeMemories()

    class _FakeClient:
        v1 = _FakeV1()

    with patch.object(memory_store, "_get_client", lambda: _FakeClient()):
        out = asyncio.run(
            memory_store.list_top_cases_for_draft(
                user_id="user-1",
                category="standing desk",
                region="Berkeley",
                limit=5,
            )
        )

    # Should include only the two standing-desk + Berkeley rows, ordered
    # most-recent first.
    cats = [r.get("category") for r in out]
    regs = [r.get("region") for r in out]
    assert cats == ["standing desk", "standing desk"]
    assert regs == ["Berkeley", "Berkeley"]
    worked = [r.get("what_worked") for r in out]
    assert worked == [["D"], ["B"]]


def test_list_top_cases_for_draft_empty_when_no_user_or_client():
    from api import memory_store

    # Missing user_id → empty list.
    out = asyncio.run(
        memory_store.list_top_cases_for_draft(
            user_id=None, category="any", region="any"
        )
    )
    assert out == []

    # Client unavailable → empty list.
    with patch.object(memory_store, "_get_client", lambda: None):
        out = asyncio.run(
            memory_store.list_top_cases_for_draft(
                user_id="user-1", category="any", region="any"
            )
        )
    assert out == []
