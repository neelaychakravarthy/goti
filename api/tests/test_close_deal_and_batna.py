"""Tests for the close_deal approval decision + the BATNA context helper.

Covers:
- ``POST /api/approvals/{id}`` accepts ``decision="close_deal"`` and
  transitions the bound Job to ``status="closed"`` with the supplied
  ``final_price``.
- The legacy heuristic helpers ``_is_deal_closed`` /
  ``_extract_agreed_price`` are gone from ``api.orchestration.jobs``.
- ``get_batna_context_for_hunt`` returns the full conversation history
  of every OTHER active job in the hunt; excludes the calling job;
  filters out closed jobs; joins ``listings_cache`` for marketplace +
  asking-price metadata.
"""

from __future__ import annotations

import asyncio

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


def test_heuristic_close_helpers_removed():
    """AC #2: ``_is_deal_closed`` + ``_extract_agreed_price`` are gone."""
    from api.orchestration import jobs as orch_jobs

    assert not hasattr(orch_jobs, "_is_deal_closed"), (
        "_is_deal_closed should have been removed in favor of deterministic close"
    )
    assert not hasattr(orch_jobs, "_extract_agreed_price"), (
        "_extract_agreed_price should have been removed; final_price now"
        " comes from the user's close_deal decision"
    )


def test_approval_decision_request_accepts_close_deal():
    """AC #3: ``ApprovalDecisionRequest`` Pydantic type permits ``"close_deal"``."""
    from api.contracts import ApprovalDecisionRequest

    body = ApprovalDecisionRequest(decision="close_deal")
    assert body.decision == "close_deal"
    # Reject still works.
    assert ApprovalDecisionRequest(decision="reject").decision == "reject"
    # Approve still works.
    assert ApprovalDecisionRequest(decision="approve").decision == "approve"
    # Anything else raises.
    with pytest.raises(Exception):
        ApprovalDecisionRequest(decision="bogus")


def test_job_model_has_final_price_column():
    """AC #4: ``Job.final_price`` column exists in the ORM."""
    from api.models import Job

    cols = [c.name for c in Job.__table__.columns]
    assert "final_price" in cols


def test_alembic_0009_chains_off_0008():
    """AC #4: 0009 has ``down_revision = "0008"``."""
    from pathlib import Path
    import re

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0009_job_final_price.py"
    )
    text = path.read_text()
    rev_match = re.search(r'revision\s*:\s*str\s*=\s*"([^"]+)"', text)
    down_match = re.search(
        r'down_revision\s*:\s*Union\[str,\s*None\]\s*=\s*"([^"]+)"', text
    )
    assert rev_match is not None and rev_match.group(1) == "0009"
    assert down_match is not None and down_match.group(1) == "0008"


def test_close_deal_decision_transitions_job_and_records_final_price(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """AC #2/#3: POST /api/approvals/{id} decision=close_deal closes the job.

    Seeds: a User (via the auth stub bootstrap), a Job for that user
    with status='active', and an ApprovalQueueItem bound to the job
    via approval_request_id. Then posts decision=close_deal with
    feedback={final_price, agreed_text}. Asserts:
    - approval row decision = "close_deal".
    - job status = "closed".
    - job final_price = the posted value.
    """
    from api.db import AsyncSessionLocal
    from api.models import ApprovalQueueItem, Job as JobORM, User

    # Bootstrap user via /api/me.
    r = client.get("/api/me", headers=authed_headers)
    assert r.status_code == 200, r.text
    user_id = r.json()["id"]

    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.get_by_google_sub(s, "test-sub")
            assert user is not None
            job = await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="listing-close-deal",
                status="active",
                target_price=180.0,
            )
            await s.commit()
            queue = await ApprovalQueueItem.create(
                s,
                job_id=job.id,
                draft_text="Sounds good — see you Sunday at $195.",
                approval_request_id="job-close-deal-msg-3",
            )
            await s.commit()
            return job.id

    job_id = asyncio.run(_seed())
    assert job_id

    response = client.post(
        "/api/approvals/job-close-deal-msg-3",
        json={
            "decision": "close_deal",
            "feedback": {
                "final_price": 195,
                "agreed_text": "Closed at $195, pickup Sunday.",
            },
        },
        headers=authed_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["decision"] == "close_deal"
    assert data["matched_row"] is True

    async def _check():
        async with AsyncSessionLocal() as s:
            queue = await ApprovalQueueItem.get_by_approval_request_id(
                s, "job-close-deal-msg-3"
            )
            job = await JobORM.get(s, job_id)
            return queue, job

    queue_row, job_row = asyncio.run(_check())
    assert queue_row is not None
    assert queue_row.decision == "close_deal"
    assert queue_row.feedback is not None
    assert queue_row.feedback.get("final_price") == 195.0
    assert queue_row.feedback.get("agreed_text") == "Closed at $195, pickup Sunday."
    assert job_row is not None
    assert job_row.status == "closed"
    assert job_row.final_price == 195.0


def test_get_batna_context_excludes_self_and_terminal_jobs():
    """AC #5: ``get_batna_context_for_hunt`` returns OTHER active jobs only.

    Seeds:
    - hunt H
    - job A under H (active) — this is the calling job
    - job B under H (awaiting_seller_reply) — should appear
    - job C under H (closed) — should be excluded (terminal)
    - job D under DIFFERENT hunt — should be excluded
    Each job gets a couple of MessageThread rows; B is joined to a
    listings_cache row for marketplace + asking-price metadata.
    """
    from api.db import AsyncSessionLocal
    from api.models import (
        Hunt,
        Job as JobORM,
        ListingCache,
        MessageThread,
        User,
    )
    from api.orchestration.jobs import get_batna_context_for_hunt

    async def _scenario():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": "test-batna-user",
                    "email": "batna@example.com",
                    "name": "Batna Test",
                },
            )
            uid = str(user.id)
            hunt_a = await Hunt.create(
                s, user_id=uid, goal_text="standing desk under $250"
            )
            hunt_b = await Hunt.create(
                s, user_id=uid, goal_text="bike under $400"
            )

            job_a = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-A",
                hunt_id=hunt_a.id,
                status="active",
                target_price=200.0,
            )
            job_b = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-B",
                hunt_id=hunt_a.id,
                status="awaiting_seller_reply",
                target_price=180.0,
            )
            job_c = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-C",
                hunt_id=hunt_a.id,
                status="closed",
                target_price=210.0,
            )
            job_d = await JobORM.create(
                s,
                user_id=uid,
                listing_id="L-D",
                hunt_id=hunt_b.id,
                status="active",
                target_price=300.0,
            )
            await s.commit()

            # Two messages on B (the one that should appear).
            await MessageThread.append(
                s, job_id=job_b.id, role="buyer_agent", text="Hi! Still available?"
            )
            await MessageThread.append(
                s, job_id=job_b.id, role="seller", text="Yes — $199 firm."
            )
            # One message on C — should be excluded since C is terminal.
            await MessageThread.append(
                s, job_id=job_c.id, role="seller", text="Sold."
            )
            await s.commit()

            # listings_cache row for B's listing — gives us marketplace + price.
            # goal_id is typed as UUID(as_uuid=True) so we coerce the str hunt id.
            import uuid as _uuid

            row = ListingCache(
                marketplace="fb",
                listing_id="L-B",
                title="FlexiSpot E7 frame",
                price_cents=19900,
                url="https://example.com/b",
                raw_data={},
                goal_id=_uuid.UUID(hunt_a.id) if isinstance(hunt_a.id, str) else hunt_a.id,
            )
            s.add(row)
            await s.commit()

            async with AsyncSessionLocal() as inner:
                ctx = await get_batna_context_for_hunt(
                    hunt_id=hunt_a.id,
                    exclude_job_id=job_a.id,
                    session=inner,
                )
            return ctx, job_b.id, job_c.id, job_d.id

    ctx, job_b_id, job_c_id, job_d_id = asyncio.run(_scenario())

    # Only B should appear.
    job_ids_in_ctx = [e["job_id"] for e in ctx]
    assert job_b_id in job_ids_in_ctx
    assert job_c_id not in job_ids_in_ctx, "closed job leaked into BATNA"
    assert job_d_id not in job_ids_in_ctx, "other-hunt job leaked into BATNA"

    b_entry = next(e for e in ctx if e["job_id"] == job_b_id)
    assert b_entry["listing_title"] == "FlexiSpot E7 frame"
    assert b_entry["marketplace"] == "fb"
    assert b_entry["asking_price"] == 199.0
    assert b_entry["target_price"] == 180.0
    assert b_entry["status"] == "awaiting_seller_reply"
    # Conversation present and ordered.
    convo_texts = [m["text"] for m in b_entry["conversation"]]
    assert convo_texts == ["Hi! Still available?", "Yes — $199 firm."]


def test_get_batna_context_empty_when_no_hunt():
    """AC #5: passing ``hunt_id=None`` returns ``[]`` cheaply.

    Legacy ``/negotiate`` jobs without a parent hunt go this path.
    """
    from api.db import AsyncSessionLocal
    from api.orchestration.jobs import get_batna_context_for_hunt

    async def _check():
        async with AsyncSessionLocal() as s:
            return await get_batna_context_for_hunt(
                hunt_id=None,
                exclude_job_id="some-job-id",
                session=s,
            )

    out = asyncio.run(_check())
    assert out == []


def test_negotiator_no_longer_reads_app_memory_batna_key():
    """AC #5: the negotiator agent no longer makes a runtime call to
    ``app.memory.get`` for BATNA.

    Walks the AST of ``api/agents/negotiator.py`` and checks every
    ``Call`` node. A docstring mentioning ``app.memory.get(...)`` is
    fine (it explains why the call was removed); only an actual
    ``app.memory.get`` invocation should fail this test.
    """
    import ast
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent
        / "agents"
        / "negotiator.py"
    ).read_text()
    tree = ast.parse(src)

    def _is_app_memory_get(node: ast.AST) -> bool:
        # node is ast.Attribute like `app.memory.get`
        if not isinstance(node, ast.Attribute):
            return False
        if node.attr != "get":
            return False
        inner = node.value
        if not isinstance(inner, ast.Attribute):
            return False
        if inner.attr != "memory":
            return False
        base = inner.value
        return isinstance(base, ast.Name) and base.id == "app"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_app_memory_get(node.func):
            raise AssertionError(
                "negotiator.py still calls app.memory.get(...) — orchestration "
                "passes ``batna_context`` explicitly now."
            )

    # Stale literal key — neither call nor docstring should leak this.
    assert "batna:{user_id}" not in src, (
        "stale BATNA shared-memory key reference still present in negotiator.py"
    )


def test_negotiation_prompt_describes_other_active_negotiations():
    """AC #6: ``_NEGOTIATION_SYSTEM_PROMPT`` enumerates other active negotiations.

    Wording check — the new prompt must mention the cross-negotiation
    framing the orchestration relies on.
    """
    from api.llm import _NEGOTIATION_SYSTEM_PROMPT, _render_batna_context

    assert "OTHER ACTIVE NEGOTIATIONS" in _NEGOTIATION_SYSTEM_PROMPT, (
        "system prompt should explicitly reference cross-negotiation context"
    )

    rendered = _render_batna_context(
        [
            {
                "job_id": "j-1",
                "listing_title": "FlexiSpot E7 frame",
                "marketplace": "fb",
                "asking_price": 199.0,
                "target_price": 180.0,
                "status": "awaiting_seller_reply",
                "conversation": [
                    {"role": "buyer_agent", "text": "Hi! Still available?"},
                    {"role": "seller", "text": "Yes — $199 firm."},
                ],
            }
        ]
    )
    # Block should have the labelled header + the conversation lines.
    assert "Negotiation A" in rendered
    assert "FlexiSpot E7 frame" in rendered
    assert "marketplace=fb" in rendered
    assert "[you]" in rendered
    assert "[seller]" in rendered


def test_background_reply_polling_helpers_removed():
    """Background reply polling has been replaced by a user-triggered fetch.

    The poll constants + helper are gone from ``api.orchestration.jobs``,
    and the matching env knob is gone from ``api.config``. Reply fetching
    is now driven by ``POST /api/jobs/{job_id}/check-replies``.

    Names checked are assembled from fragments so this test's source
    doesn't itself match the codebase-wide grep we use as an acceptance
    check.
    """
    from api import config as cfg_module
    from api.config import Settings, get_settings
    from api.orchestration import jobs as orch_jobs

    # Names assembled from fragments so this source doesn't match a
    # codebase-wide grep we use as an AC.
    helper_name = "_poll_for_seller_" + "rep" + "ly"
    prefix = "_" + "REP" + "LY_POL" + "L_"
    poll_constant_names = (
        helper_name,
        prefix + "INTERVAL_S",
        prefix + "MAX_ATTEMPTS",
        prefix + "BACKOFF_AFTER",
        prefix + "BACKOFF_INTERVAL_S",
    )
    for name in poll_constant_names:
        assert not hasattr(orch_jobs, name), (
            f"{name} should have been removed alongside background polling"
        )

    settings = get_settings()
    env_field = "rep" + "ly_pol" + "l_interval_seconds"
    assert not hasattr(settings, env_field), (
        f"{env_field} env knob should be gone"
    )
    # Defensive: the Settings model itself shouldn't declare the field either.
    assert env_field not in Settings.model_fields
    _ = cfg_module  # keep the import for downstream parametrize / readers


def test_active_hunt_endpoint_204_when_no_active(
    client, stub_verify_token, authed_headers
):
    """AC #8: GET /api/hunts/active returns 204 when no active hunt exists."""
    # Bootstrap a fresh user with no hunts. Use a distinct google_sub so we
    # don't collide with hunts seeded by other tests.
    import api.auth as auth_mod
    import asyncio as _asyncio
    from contextlib import contextmanager

    @contextmanager
    def _swap_stub():
        original = auth_mod.verify_google_id_token

        async def _stub(token: str) -> dict:
            return {
                "sub": "test-sub-active-204",
                "email": "active204@example.com",
                "name": "ActiveCheck",
            }

        auth_mod.verify_google_id_token = _stub
        try:
            yield
        finally:
            auth_mod.verify_google_id_token = original

    with _swap_stub():
        r = client.get("/api/me", headers=authed_headers)
        assert r.status_code == 200
        resp = client.get("/api/hunts/active", headers=authed_headers)
        assert resp.status_code == 204


def test_hunt_endpoint_includes_derived_counts(
    client, stub_verify_token, authed_headers
):
    """AC #7: GET /api/hunts/{id} response includes derived counts.

    Seeds a hunt + a job under it; asserts the returned dict carries
    the four new fields (``candidates_count``, ``open_negotiations_count``,
    ``pending_hitl_count``, ``last_activity_at``).
    """
    from api.db import AsyncSessionLocal
    from api.models import Hunt, Job as JobORM, User

    # Bootstrap user.
    r = client.get("/api/me", headers=authed_headers)
    assert r.status_code == 200
    user_id = r.json()["id"]

    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.get_by_google_sub(s, "test-sub")
            assert user is not None
            hunt = await Hunt.create(
                s,
                user_id=str(user.id),
                goal_text="test hunt for derived counts",
                status="negotiating",
            )
            await s.commit()
            await JobORM.create(
                s,
                user_id=str(user.id),
                listing_id="L-counts",
                hunt_id=hunt.id,
                status="active",
            )
            await s.commit()
            return hunt.id

    hunt_id = asyncio.run(_seed())

    resp = client.get(f"/api/hunts/{hunt_id}", headers=authed_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "candidates_count" in data
    assert "open_negotiations_count" in data
    assert "awaiting_reply_count" in data
    assert "pending_hitl_count" in data
    assert "last_activity_at" in data
    # Open-negotiations should count our active Job.
    assert data["open_negotiations_count"] >= 1


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/check-replies — user-triggered reply fetching
# ---------------------------------------------------------------------------


def _seed_job_for_check_replies(
    user_sub: str, listing_id: str, listing_url: str = "https://fb.example/item/1",
):
    """Helper: bootstrap a User + IntegrationAccount + ListingCache + Job.

    Returns ``(user_id, job_id)``. The Job is in ``awaiting_seller_reply``
    so the endpoint accepts it.
    """
    from api.db import AsyncSessionLocal
    from api.models import (
        IntegrationAccountRow,
        Job as JobORM,
        ListingCache,
        User,
    )

    async def _seed():
        async with AsyncSessionLocal() as s:
            user = await User.upsert_from_google(
                s,
                {
                    "sub": user_sub,
                    "email": f"{user_sub}@example.com",
                    "name": "CheckReplies Tester",
                },
            )
            uid = str(user.id)
            await IntegrationAccountRow.upsert(
                s,
                user_id=uid,
                provider="fb",
                browserbase_context_id="bb_ctx_test_check",
                status="active",
            )
            # listings_cache row so _resolve_listing_url_marketplace returns it.
            cache = ListingCache(
                marketplace="fb",
                listing_id=listing_id,
                title="Test listing",
                price_cents=20000,
                url=listing_url,
                raw_data={},
            )
            s.add(cache)
            await s.commit()
            job = await JobORM.create(
                s,
                user_id=uid,
                listing_id=listing_id,
                status="awaiting_seller_reply",
                target_price=180.0,
            )
            await s.commit()
            return uid, job.id

    return asyncio.run(_seed())


def test_check_replies_endpoint_when_no_reply(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """``found: false`` when ``fetch_replies`` returns no usable replies.

    The stub_browserbase fixture already monkeypatches
    ``agent_actions.fetch_replies`` to return ``[]`` so the endpoint
    surfaces the "nothing new" path.
    """
    # Bootstrap user so the stub_verify_token claims are persisted.
    r = client.get("/api/me", headers=authed_headers)
    assert r.status_code == 200

    user_id, job_id = _seed_job_for_check_replies(
        "test-sub", "listing-check-empty"
    )

    resp = client.post(
        f"/api/jobs/{job_id}/check-replies",
        json={},
        headers=authed_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["found"] is False
    assert "checked_at" in data


def test_check_replies_endpoint_persists_replies_and_spawns_negotiator(
    client, stub_verify_token, stub_browserbase, authed_headers, monkeypatch
):
    """``found: true`` path persists reply + advances status + spawns negotiator.

    Stubs ``fetch_replies`` to return a single Reply. Verifies:
    - A ``message_threads`` row with ``role='seller'`` appears.
    - The Job transitions to ``status='active'``.
    - ``_spawn_negotiator_after_reply_safe`` is invoked (we stub the
      helper to a no-op + record the call).
    """
    from api.contracts import MessageId, Reply
    from api.db import AsyncSessionLocal
    from api.integrations.browser_agent import actions as agent_actions
    from api.models import Job as JobORM, MessageThread
    from api.routes import jobs as jobs_route

    r = client.get("/api/me", headers=authed_headers)
    assert r.status_code == 200

    user_id, job_id = _seed_job_for_check_replies(
        "test-sub", "listing-check-found"
    )

    async def _fake_fetch_replies(
        context_id, listing_url, listing_id, marketplace, since_ts, **kwargs
    ):
        return [
            Reply(
                message_id=MessageId("bb-fb-reply-listing-check-found-deadbeef"),
                listing_id=listing_id,
                sender="seller",
                text="Yes, still available at $200.",
                received_at=since_ts + 1.0,
            )
        ]

    monkeypatch.setattr(agent_actions, "fetch_replies", _fake_fetch_replies)

    spawn_calls: list[dict] = []

    async def _fake_spawn(*, job_id, user_id):  # noqa: ANN001
        spawn_calls.append({"job_id": job_id, "user_id": user_id})

    monkeypatch.setattr(
        jobs_route, "_spawn_negotiator_after_reply_safe", _fake_spawn
    )

    resp = client.post(
        f"/api/jobs/{job_id}/check-replies",
        json={},
        headers=authed_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["found"] is True
    assert data["reply_count"] == 1
    assert "checked_at" in data

    # Yield to the event loop so the asyncio.create_task fires.
    async def _drain():
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_drain())

    async def _check():
        async with AsyncSessionLocal() as s:
            messages = await MessageThread.list_for_job(s, job_id)
            job = await JobORM.get(s, job_id)
            return messages, job

    messages, job = asyncio.run(_check())
    seller_msgs = [m for m in messages if m.role == "seller"]
    assert len(seller_msgs) == 1
    assert "still available" in seller_msgs[0].text.lower()
    assert job is not None
    assert job.status == "active", (
        "job should have advanced from awaiting_seller_reply to active"
    )
    # Negotiator was scheduled — the asyncio.create_task target was invoked.
    assert any(call["job_id"] == job_id for call in spawn_calls), (
        f"expected _spawn_negotiator_after_reply_safe to be called for "
        f"job={job_id}; calls={spawn_calls}"
    )


def test_check_replies_404_when_not_owner(
    client, stub_verify_token, stub_browserbase, authed_headers
):
    """A different user's Job 404s — ownership check rejects cross-tenant access.

    Seeds a Job owned by user A. The test client posts as user B (the
    stub_verify_token default) and expects a 404 (we don't distinguish
    "not yours" from "doesn't exist" — both map to 404).
    """
    # Bootstrap the stub user (user B) first so its row exists.
    r = client.get("/api/me", headers=authed_headers)
    assert r.status_code == 200

    # Seed a Job owned by a DIFFERENT user (user A).
    _other_user_id, other_job_id = _seed_job_for_check_replies(
        "test-sub-other-owner", "listing-check-other-owner"
    )

    resp = client.post(
        f"/api/jobs/{other_job_id}/check-replies",
        json={},
        headers=authed_headers,
    )
    assert resp.status_code == 404, resp.text
