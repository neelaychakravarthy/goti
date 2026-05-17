"""Phase G' — post-close analyzer reasoner tests.

Covers:
- ``analyze_negotiation`` reasoner is callable + decorated with @app.reasoner().
- ``clarifier.main()`` imports the analyzer module so the decorator fires.
- ``run_post_close_analysis`` fans out N parallel ``analyze_negotiation``
  reasoner calls — one per closed job.
- The JSON round-trip works: an analyzer dict is JSON-encoded into the
  EverOS ``content`` field, then ``_case_from_dict`` parses it back.
- Missing EVEROS_API_KEY degrades gracefully — no exceptions raised, the
  reasoner still runs but the persist step is skipped.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

# Disable Postgres-only alembic migrations during test boot (SQLite path).
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


def test_analyzer_module_exports_reasoner():
    from api.agents import analyzer

    assert hasattr(analyzer, "analyze_negotiation")
    assert callable(analyzer.analyze_negotiation)


def test_clarifier_main_imports_analyzer():
    """clarifier.main() imports the analyzer module so the decorator fires."""
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent / "agents" / "clarifier.py"
    )
    text = path.read_text()
    assert "analyzer," in text, (
        "clarifier.main() must import api.agents.analyzer so the "
        "@app.reasoner() decorator fires when the agent server boots."
    )


def test_analyzer_contract_coerces_output():
    """The reasoner coerces non-strict LLM output to the expected shape."""
    from api.agents import analyzer

    async def _fake_analyze(*args, **kwargs):
        return {
            "what_worked": ["Anchored low", "  ", 42],
            "what_didnt": ["Took too long to counter"],
            "key_moments": [
                {"turn_idx": 2, "observation": "Seller dropped 10%"},
                {"turn_idx": "x", "observation": "ignored"},
                {"observation": "missing turn"},
                "garbage",
            ],
            "tactical_lessons": ["Open with a competing offer cite"],
            "category": "  standing desk  ",
            "region": "Berkeley",
            "confidence": "0.82",
        }

    with patch("api.agents.analyzer.analyze_full_negotiation", _fake_analyze):
        out = asyncio.run(
            analyzer.analyze_negotiation(
                negotiation_transcript=[],
                listing={"id": "L-1"},
                outcome="closed_deal",
            )
        )
    assert out["what_worked"] == ["Anchored low"]
    assert out["what_didnt"] == ["Took too long to counter"]
    # turn_idx coerced to int; non-int and missing entries dropped.
    assert out["key_moments"] == [
        {"turn_idx": 2, "observation": "Seller dropped 10%"},
        {"turn_idx": 0, "observation": "ignored"},
        {"turn_idx": 0, "observation": "missing turn"},
    ]
    assert out["tactical_lessons"] == ["Open with a competing offer cite"]
    assert out["category"] == "standing desk"
    assert out["region"] == "Berkeley"
    assert out["confidence"] == 0.82
    assert out["outcome"] == "closed_deal"


def test_analyzer_falls_back_on_llm_exception():
    """If analyze_full_negotiation raises, the reasoner returns the safe fallback."""
    from api.agents import analyzer

    async def _boom(*args, **kwargs):
        raise RuntimeError("Anthropic exploded")

    with patch("api.agents.analyzer.analyze_full_negotiation", _boom):
        out = asyncio.run(
            analyzer.analyze_negotiation(
                negotiation_transcript=[],
                listing={},
                outcome="declined",
            )
        )
    assert out["what_worked"] == []
    assert out["what_didnt"] == []
    assert out["key_moments"] == []
    assert out["tactical_lessons"] == []
    assert out["confidence"] == 0.0
    assert out["outcome"] == "declined"
    assert "error" in out


def test_run_post_close_analysis_fans_out_parallel(stub_verify_token):
    """One analyze_negotiation invocation per closed job; all fire concurrently."""
    from api.models import (
        Hunt,
        Job as JobORM,
        ListingCache,
        MessageThread,
        User,
    )
    from api.orchestration import analyzer as orch_analyzer

    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "test-analyzer-fanout",
                    "email": "fanout@example.com",
                    "name": "Fanout",
                },
            )
            uid = str(user.id)
            hunt = await Hunt.create(
                s,
                user_id=uid,
                goal_text="standing desk under 250",
                status="closed",
                budget=250.0,
            )
            await s.commit()
            import uuid as _uuid

            for li in ("L-W", "L-S1", "L-S2"):
                s.add(
                    ListingCache(
                        marketplace="fb",
                        listing_id=li,
                        title=f"Desk {li}",
                        price_cents=24000,
                        url=f"https://example.com/{li}",
                        raw_data={"id": li, "marketplace": "fb"},
                        goal_id=_uuid.UUID(hunt.id),
                    )
                )
            await s.commit()

            winner = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-W",
                hunt_id=hunt.id,
                status="closed",
                target_price=200.0,
            )
            await JobORM.close_at_price(s, winner.id, 210.0)
            sib1 = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-S1",
                hunt_id=hunt.id,
                status="closed",
                target_price=210.0,
            )
            sib2 = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-S2",
                hunt_id=hunt.id,
                status="closed",
                target_price=215.0,
            )
            await s.commit()
            # Seed some buyer-agent messages so the outcome classifier
            # tags siblings as "declined" rather than "abandoned".
            await MessageThread.append(
                s, job_id=sib1.id, role="buyer_agent", text="Hi, interested!"
            )
            await MessageThread.append(
                s,
                job_id=sib2.id,
                role="buyer_agent",
                text="Hi, would you take $200?",
            )
            await s.commit()
            return uid, hunt.id, winner.id, sib1.id, sib2.id

    uid, hunt_id, winner_id, sib1_id, sib2_id = asyncio.run(_seed())

    seen_jobs: list[str] = []

    async def _fake_invoke(method, payload, *args, **kwargs):
        assert method == "analyze_negotiation"
        # ``listing.id`` should be present so the analyzer knows which
        # job it's analyzing.
        listing = payload.get("listing")
        seen_jobs.append(listing.get("id") if isinstance(listing, dict) else None)
        return {
            "what_worked": ["Cited a competing offer"],
            "what_didnt": [],
            "key_moments": [],
            "tactical_lessons": ["Open with leverage"],
            "category": "standing desk",
            "region": "",
            "confidence": 0.7,
            "outcome": payload.get("outcome"),
        }

    write_calls: list[tuple[str, dict]] = []

    async def _fake_write(*, user_id, job_id, analysis):  # noqa: ANN001
        write_calls.append((job_id, analysis))
        return True

    with (
        patch.object(orch_analyzer, "invoke_reasoner", _fake_invoke),
        patch.object(orch_analyzer, "_write_analyzed_case", _fake_write),
    ):
        result = asyncio.run(
            orch_analyzer.run_post_close_analysis(hunt_id=hunt_id, user_id=uid)
        )

    assert result["ok"] is True
    assert result["analyzed_count"] == 3
    assert result["skipped_count"] == 0
    assert set(seen_jobs) == {"L-W", "L-S1", "L-S2"}
    # Confirm each closed job got a write.
    written_job_ids = {jid for (jid, _analysis) in write_calls}
    assert written_job_ids == {winner_id, sib1_id, sib2_id}


def test_run_post_close_analysis_handles_missing_hunt():
    from api.orchestration import analyzer as orch_analyzer

    result = asyncio.run(
        orch_analyzer.run_post_close_analysis(
            hunt_id="00000000-0000-0000-0000-000000000000",
            user_id="some-uid",
        )
    )
    assert result["ok"] is False
    assert result["analyzed_count"] == 0


def test_run_post_close_analysis_skips_when_everos_key_missing(
    stub_verify_token, monkeypatch
):
    """Without EVEROS_API_KEY, the EverOS write is skipped but reasoner still runs."""
    from api.models import Hunt, Job as JobORM, User
    from api.orchestration import analyzer as orch_analyzer

    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "test-analyzer-noeveros",
                    "email": "noeveros@example.com",
                    "name": "No EverOS",
                },
            )
            uid = str(user.id)
            hunt = await Hunt.create(
                s,
                user_id=uid,
                goal_text="bike",
                status="closed",
                budget=300.0,
            )
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-noev",
                hunt_id=hunt.id,
                status="closed",
                target_price=250.0,
            )
            await JobORM.close_at_price(s, job.id, 260.0)
            await s.commit()
            return uid, hunt.id

    uid, hunt_id = asyncio.run(_seed())

    async def _fake_invoke(method, payload, *args, **kwargs):
        return {
            "what_worked": ["Anchored low"],
            "what_didnt": [],
            "key_moments": [],
            "tactical_lessons": ["Open with leverage"],
            "category": "bike",
            "region": "",
            "confidence": 0.6,
            "outcome": payload.get("outcome"),
        }

    # Force the EverOS settings to be empty so the write path bails.
    from api.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "everos_api_key", "")

    with patch.object(orch_analyzer, "invoke_reasoner", _fake_invoke):
        result = asyncio.run(
            orch_analyzer.run_post_close_analysis(hunt_id=hunt_id, user_id=uid)
        )

    # ``run_post_close_analysis`` returns ok=True even when the
    # persistence step is skipped — the reasoner ran, the write degraded.
    assert result["ok"] is True
    # analyzed_count counts successful reasoner runs (write_ok or not).
    assert result["analyzed_count"] == 1


def test_case_from_dict_parses_analyzer_json_content():
    """``_case_from_dict`` extracts category/region/outcome from the JSON content."""
    import json
    from api.memory_store import _case_from_dict, _extract_analyzer_payload

    analysis = {
        "what_worked": ["Anchored at $200"],
        "what_didnt": ["Waited too long"],
        "key_moments": [{"turn_idx": 3, "observation": "Seller blinked"}],
        "tactical_lessons": ["Open with a competitor cite"],
        "category": "standing desk",
        "region": "Berkeley",
        "confidence": 0.8,
        "outcome": "closed_deal",
    }
    item = {
        "id": "case-123",
        "session_id": "goti-analysis-job-abc",
        "timestamp": "2026-05-22T10:00:00Z",
        "content": json.dumps(analysis),
    }
    case = _case_from_dict(item, default_user_id="user-1")
    assert case is not None
    assert case.category == "standing desk"
    assert case.region == "Berkeley"
    assert case.outcome == "closed_deal"
    # Title falls back to "<category> negotiation" when task_intent is missing.
    assert "standing desk" in case.title.lower()
    # And the analyzer extractor returns the parsed payload for downstream use.
    extracted = _extract_analyzer_payload(item)
    assert extracted is not None
    assert extracted["category"] == "standing desk"
    assert extracted["tactical_lessons"] == ["Open with a competitor cite"]


def test_case_from_dict_falls_back_for_legacy_transcript_shape():
    """When ``content`` isn't JSON, the legacy ``summary``/``approach`` fields still surface."""
    from api.memory_store import _case_from_dict

    item = {
        "id": "case-legacy",
        "title": "Bike negotiation",
        "summary": "Negotiated $250 bike down to $220",
        "outcome": "closed_deal",
        "category": "bike",
        "region": "Oakland",
        "final_price": 220,
        "timestamp": "2026-05-20T10:00:00Z",
        # NOT a JSON dump — old transcript-shape Cases come back like this.
        "content": "user: Hi, is this still available?\nassistant: Yes!",
    }
    case = _case_from_dict(item, default_user_id="user-1")
    assert case is not None
    assert case.title == "Bike negotiation"
    assert case.summary == "Negotiated $250 bike down to $220"
    assert case.final_price == 220.0
    assert case.category == "bike"
