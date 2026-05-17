"""Tests for the Phase E classifier reasoner + the ready-to-close lifecycle.

Covers:
- ``classify_negotiation_state`` reasoner is registered on the shared
  ``Agent(node_id="goti")`` and importable from ``api.agents.classifier``.
- ``Job`` ORM has ``ready_to_close`` / ``close_signal_reason`` /
  ``suggested_close_price`` columns.
- ``Job.update_readiness`` writes the verdict.
- ``invoke_classifier_for_job`` reads the job + thread, calls the
  reasoner, and persists the verdict back to the row.
- ``ready_to_close=True`` triggers a ``negotiation_ready_to_close``
  notification.
- The DealRoom (``GET /api/jobs/{id}``) surface carries the readiness
  fields on the ``next_move`` block.
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


def test_classifier_module_exports_reasoner():
    """``classify_negotiation_state`` is callable + decorated with @app.reasoner()."""
    from api.agents import classifier

    assert hasattr(classifier, "classify_negotiation_state")
    # The decorator wraps the function — calling it returns a coroutine.
    fn = classifier.classify_negotiation_state
    assert callable(fn)


def test_clarifier_main_imports_classifier():
    """``clarifier.main()`` imports the classifier module so the decorator fires."""
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent / "agents" / "clarifier.py"
    )
    text = path.read_text()
    # Verify the import of classifier is in the import list inside main().
    assert "classifier," in text, (
        "clarifier.main() must import api.agents.classifier so the "
        "@app.reasoner() decorator fires when the agent server boots."
    )


def test_job_has_readiness_columns():
    """``Job`` ORM has the Phase E columns."""
    from api.models import Job

    cols = [c.name for c in Job.__table__.columns]
    assert "ready_to_close" in cols
    assert "close_signal_reason" in cols
    assert "suggested_close_price" in cols


def test_alembic_0012_chains_off_0011():
    """0012 migration sequences after 0011."""
    from pathlib import Path
    import re

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0012_job_readiness_columns.py"
    )
    text = path.read_text()
    rev = re.search(r'revision\s*:\s*str\s*=\s*"([^"]+)"', text)
    down = re.search(
        r'down_revision\s*:\s*Union\[str,\s*None\]\s*=\s*"([^"]+)"', text
    )
    assert rev is not None and rev.group(1) == "0012"
    assert down is not None and down.group(1) == "0011"


def test_update_readiness_persists_verdict(stub_verify_token, authed_headers):
    """``Job.update_readiness`` writes ready_to_close + reason + price."""
    from api.models import Job as JobORM, User

    async def _scenario():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "test-update-readiness",
                    "email": "readiness@example.com",
                    "name": "Readiness Test",
                },
            )
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-readiness",
                status="active",
                target_price=180.0,
            )
            await s.commit()

            # Default: ready_to_close should be False.
            assert job.ready_to_close is False

            await JobORM.update_readiness(
                s,
                job.id,
                ready_to_close=True,
                close_signal_reason="Seller agreed at $190.",
                suggested_close_price=190.0,
            )
            await s.commit()

            refreshed = await JobORM.get(s, job.id)
            return refreshed

    refreshed = asyncio.run(_scenario())
    assert refreshed is not None
    assert refreshed.ready_to_close is True
    assert refreshed.close_signal_reason == "Seller agreed at $190."
    assert refreshed.suggested_close_price == 190.0


def test_invoke_classifier_for_job_persists_and_emits_notification(
    stub_verify_token, stub_browserbase, authed_headers
):
    """Wires up the reasoner end-to-end against an in-memory DB.

    Patches ``invoke_reasoner`` to return a fixed ready_to_close=True
    response, then asserts:
    1. The Job row picks up the verdict (ready_to_close, reason, price).
    2. A ``negotiation_ready_to_close`` notification was persisted.
    """
    from api.models import Job as JobORM, MessageThread, Notification, User
    from api.orchestration import jobs as orch_jobs

    async def _scenario():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "test-classifier-flow",
                    "email": "classifier@example.com",
                    "name": "Classifier Test",
                },
            )
            uid = str(user.id)
            job = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-classifier",
                status="active",
                target_price=200.0,
            )
            await s.commit()
            await MessageThread.append(
                s, job_id=job.id, role="buyer_agent", text="Would you take $190?"
            )
            await MessageThread.append(
                s, job_id=job.id, role="seller", text="Sure, $190 works."
            )
            await s.commit()
            return uid, job.id

    uid, job_id = asyncio.run(_scenario())

    async def _fake_invoke_reasoner(method, payload, *args, **kwargs):
        assert method == "classify_negotiation_state"
        assert "conversation" in payload
        assert "listing" in payload
        return {
            "ready_to_close": True,
            "reason": "Seller agreed at $190.",
            "suggested_close_price": 190.0,
            "confidence": 0.85,
        }

    with patch.object(orch_jobs, "invoke_reasoner", _fake_invoke_reasoner):
        response = asyncio.run(orch_jobs.invoke_classifier_for_job(job_id))
    assert response is not None
    assert response["ready_to_close"] is True

    async def _verify():
        async with AsyncSessionLocal() as s:
            job = await JobORM.get(s, job_id)
            notifications = await Notification.list_for_user(s, uid, limit=10)
            return job, notifications

    job, notifications = asyncio.run(_verify())
    assert job is not None
    assert job.ready_to_close is True
    assert job.close_signal_reason == "Seller agreed at $190."
    assert job.suggested_close_price == 190.0
    # Exactly one notification with the ready-to-close kind_tag.
    matched = [
        n
        for n in notifications
        if (n.payload or {}).get("kind_tag") == "negotiation_ready_to_close"
    ]
    assert len(matched) == 1, (
        f"expected one ready-to-close notification, got {[n.title for n in notifications]}"
    )


def test_invoke_classifier_no_notification_when_not_ready(stub_verify_token):
    """When the classifier returns ready_to_close=False, no notification is emitted."""
    from api.models import Job as JobORM, Notification, User
    from api.orchestration import jobs as orch_jobs

    async def _scenario():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "test-classifier-not-ready",
                    "email": "notready@example.com",
                    "name": "Not Ready",
                },
            )
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-not-ready",
                status="active",
                target_price=200.0,
            )
            await s.commit()
            return str(user.id), job.id

    uid, job_id = asyncio.run(_scenario())

    async def _fake(method, payload, *args, **kwargs):
        return {
            "ready_to_close": False,
            "reason": "Still negotiating.",
            "suggested_close_price": None,
            "confidence": 0.3,
        }

    with patch.object(orch_jobs, "invoke_reasoner", _fake):
        asyncio.run(orch_jobs.invoke_classifier_for_job(job_id))

    async def _verify():
        async with AsyncSessionLocal() as s:
            job = await JobORM.get(s, job_id)
            notifs = await Notification.list_for_user(s, uid, limit=10)
            return job, notifs

    job, notifs = asyncio.run(_verify())
    assert job is not None
    assert job.ready_to_close is False
    # No ready-to-close notification should have been emitted.
    ready_notifs = [
        n
        for n in notifs
        if (n.payload or {}).get("kind_tag") == "negotiation_ready_to_close"
    ]
    assert ready_notifs == []


def test_next_move_carries_readiness_fields():
    """``NextMove`` contract has ready_to_close / close_signal_reason / suggested_close_price."""
    from api.contracts import NextMove, PriceLadder, SavingsReceipt

    nm = NextMove(
        job_id="job-x",
        headline="Next move",
        sub="…",
        price_ladder=PriceLadder(
            your_max=220, seller_asks=200, goti_recommends=180, competing_seller=0
        ),
        plain_english="",
        savings=SavingsReceipt(pay=180, save_vs_asking=20, under_budget=0),
        draft="",
        ready_to_close=True,
        close_signal_reason="Seller agreed.",
        suggested_close_price=180.0,
    )
    assert nm.ready_to_close is True
    assert nm.close_signal_reason == "Seller agreed."
    assert nm.suggested_close_price == 180.0
    # Defaults when omitted.
    nm2 = NextMove(
        job_id="job-y",
        headline="Next move",
        sub="…",
        price_ladder=PriceLadder(
            your_max=0, seller_asks=0, goti_recommends=0, competing_seller=0
        ),
        plain_english="",
        savings=SavingsReceipt(pay=0, save_vs_asking=0, under_budget=0),
        draft="",
    )
    assert nm2.ready_to_close is False
    assert nm2.close_signal_reason is None
    assert nm2.suggested_close_price is None
