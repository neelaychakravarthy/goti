"""End-to-end test for the hunt lifecycle.

Walks through the full flow:

1. ``POST /api/goals`` creates a Hunt + spawns the background lifecycle.
2. The lifecycle invokes ``ask_clarifying_question`` which pauses → the
   bridge router creates a ``clarifying_question`` notification +
   approval row.
3. We assert the notification appears on ``GET /api/notifications``.
4. ``POST /api/approvals/{id}`` with ``{decision: approve,
   feedback: {budget: 250}}`` resolves the pause; the lifecycle's
   stubbed reasoner-client returns the budget, the hunt advances to
   ``discovering`` → discovery (stubbed) → valuation (stubbed) →
   ``awaiting_picks``.
5. ``pick_listings`` pauses again; the bridge synthesises another
   notification (kind=``listings_found``).
6. We assert that new notification + that ``GET /api/hunts/{hunt_id}``
   reports ``awaiting_picks`` or ``negotiating``.

External dependencies (Browserbase, LLM, AgentField
control plane) are stubbed via ``unittest.mock.patch`` and the
``stub_discovery`` / ``stub_browserbase`` / ``stub_verify_token``
fixtures from ``conftest.py``. ``invoke_reasoner`` is monkeypatched to
simulate the reasoner-client side of the pause/resume bridge.
"""

from __future__ import annotations

import asyncio
import time

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
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Reasoner-client stub
#
# The hunt lifecycle calls ``invoke_reasoner(method, input, timeout, raise_on_error)``
# to dispatch to the AgentField agent server. In a unit test there's no
# agent server — so we patch the invoke_reasoner symbol that the lifecycle
# imports, and simulate the pause/resume bridge:
#
# - For ``ask_clarifying_question`` and ``pick_listings`` (the pause-points)
#   we PRE-POST a request-approval call so the bridge creates the
#   notification + queue row; then wait for the user (the test) to POST
#   /api/approvals/{id}; then read the resolved feedback off the queue and
#   return the reasoner's post-resume return dict.
# - For ``assess_listing`` (no pause) we just return a stubbed valuation.
# - For ``draft_message`` (per-job lifecycle) we likewise simulate the
#   pause-and-wait, but the integration test only exercises through phase
#   3 (pick) — phase 4 (per-job lifecycle) is tested in isolation below.
# ---------------------------------------------------------------------------


_CALLBACK_BASE = "http://127.0.0.1:8080"


async def _post_request_approval(
    *,
    fastapi_client,  # unused — kept for API compat
    approval_request_id: str,
    payload: dict,
) -> None:
    """Invoke the bridge's request-approval handler directly.

    Avoids the TestClient → event-loop reentrancy issue (TestClient is
    sync + we're running inside a running event loop). The bridge
    function is a coroutine; we can call it with a fresh DB session.

    The bridge route enforces a loopback-origin check via the FastAPI
    ``request`` arg; we synthesize a minimal ``Request`` with a 127.0.0.1
    client so the check passes.
    """
    from starlette.requests import Request as _StarRequest

    from api.db import AsyncSessionLocal
    from api.routes.agent_bridge import RequestApprovalBody, request_approval

    body = RequestApprovalBody(
        approval_request_id=approval_request_id,
        callback_url=f"{_CALLBACK_BASE}/webhooks/approval",
        expires_in_hours=72,
        payload=payload,
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/agents/goti/executions/test-exec/request-approval",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "query_string": b"",
    }
    fake_request = _StarRequest(scope)
    async with AsyncSessionLocal() as session:
        await request_approval(
            node="goti",
            execution_id="test-exec",
            body=body,
            request=fake_request,
            session=session,
        )


async def _wait_for_decision(
    approval_request_id: str, timeout_seconds: float = 30.0
) -> dict | None:
    """Poll the approval_queue until a decision is set; return the feedback."""
    from api.db import AsyncSessionLocal
    from api.models import ApprovalQueueItem

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        async with AsyncSessionLocal() as session:
            row = await ApprovalQueueItem.get_by_approval_request_id(
                session, approval_request_id
            )
            if row is not None and row.decision is not None:
                return row.feedback
        await asyncio.sleep(0.1)
    return None


@pytest.mark.asyncio
async def test_hunt_lifecycle_end_to_end(
    monkeypatch, client, stub_verify_token, stub_discovery, stub_browserbase, authed_headers
):
    """AC #6: full happy-path walk-through of the hunt lifecycle."""

    # ---- Patch invoke_reasoner to simulate the agent server ----
    from api.orchestration import agents_client as ac_module
    from api.orchestration import hunts as orch_hunts
    from api.orchestration import jobs as orch_jobs

    invocations: list[tuple[str, dict]] = []

    async def fake_invoke_reasoner(
        method: str,
        input: dict,
        *,
        timeout: float = 60.0,
        raise_on_error: bool = True,
    ) -> dict:
        invocations.append((method, input))
        hunt_id = input.get("hunt_id") or ""
        if method == "ask_clarifying_question":
            approval_id = f"hunt-{hunt_id}-budget"
            # Simulate the reasoner's request-approval call onto the bridge
            await _post_request_approval(
                fastapi_client=fastapi_client,
                approval_request_id=approval_id,
                payload={
                    "kind": "clarifying_question",
                    "title": "What's your budget?",
                    "body": "Whats your budget for this item?",
                    "hunt_id": hunt_id,
                    "user_id": input.get("user_id", "demo_user"),
                    "target_href": f"/start?hunt_id={hunt_id}&q=budget",
                    "question": "Whats your budget?",
                },
            )
            feedback = await _wait_for_decision(approval_id, timeout_seconds=15.0)
            budget = None
            if isinstance(feedback, dict):
                inner = feedback.get("feedback")
                if isinstance(inner, dict):
                    budget = inner.get("budget")
                elif inner is not None:
                    budget = inner
                if budget is None:
                    budget = feedback.get("budget") or feedback.get("edited_text")
            try:
                budget_f = float(budget) if budget is not None else None
            except (TypeError, ValueError):
                budget_f = None
            return {
                "clarifying_question": "Whats your budget?",
                "budget": budget_f,
                "approval_status": "approved",
            }
        if method == "assess_listing":
            listing = input.get("listing", {})
            price = float(listing.get("price", 100.0))
            return {
                "fair_price_estimate": price,
                "walk_away_price": price * 1.05,
                "target_price": price * 0.9,
                "reasoning": "stub",
            }
        if method == "pick_listings":
            approval_id = f"hunt-{hunt_id}-pick"
            await _post_request_approval(
                fastapi_client=fastapi_client,
                approval_request_id=approval_id,
                payload={
                    "kind": "listings_found",
                    "title": f"Found {len(input.get('listings_with_valuations', []))} listings",
                    "body": "Pick which listings to negotiate.",
                    "hunt_id": hunt_id,
                    "user_id": input.get("user_id", "demo_user"),
                    "target_href": f"/chat?hunt_id={hunt_id}",
                    "count": len(input.get("listings_with_valuations", [])),
                },
            )
            feedback = await _wait_for_decision(approval_id, timeout_seconds=15.0)
            picked: list[str] = []
            if isinstance(feedback, dict):
                inner = feedback.get("feedback")
                if isinstance(inner, dict):
                    picked = inner.get("picked_listing_ids") or []
                elif feedback.get("picked_listing_ids"):
                    picked = feedback.get("picked_listing_ids")
            return {
                "picked_listing_ids": picked,
                "approval_status": "approved",
            }
        if method == "draft_message":
            # The per-job lifecycle will call this; for this test we
            # don't drive it to completion. Return a stub indicating
            # "no draft / cancelled" so the per-job lifecycle exits.
            return {
                "draft_text": "Hi, is this still available?",
                "draft_reasoning": "stub opener",
                "approval_status": "rejected",
                "sent_text": None,
                "approval_request_id": "stub",
            }
        return {"error": f"unhandled method in stub: {method}"}

    # Patch on the module that the lifecycle imports from.
    monkeypatch.setattr(ac_module, "invoke_reasoner", fake_invoke_reasoner)
    monkeypatch.setattr(orch_hunts.agents_client, "invoke_reasoner", fake_invoke_reasoner)
    # The jobs lifecycle module also calls invoke_reasoner directly.
    monkeypatch.setattr(orch_jobs, "invoke_reasoner", fake_invoke_reasoner)

    fastapi_client = client

    # ---- Step 1: POST /api/goals ----
    response = fastapi_client.post(
        "/api/goals",
        json={"text": "standing desk under $250 SF"},
        headers=authed_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    hunt_id = data["hunt_id"]
    assert hunt_id

    # Look up the User id we just minted via the auth stub so the
    # notification poll filters on the right user_id.
    from api.db import AsyncSessionLocal
    from api.models import User

    async with AsyncSessionLocal() as session:
        u = await User.get_by_google_sub(session, "test-sub")
        assert u is not None
        user_uuid = str(u.id)

    # ---- Step 2: wait for clarifier pause notification ----
    matching: list[dict] = []
    for _ in range(60):  # up to ~6s
        time.sleep(0.1)
        resp = fastapi_client.get(
            "/api/notifications", headers=authed_headers
        )
        assert resp.status_code == 200
        notifications = resp.json()
        matching = [
            n
            for n in notifications
            if n.get("kind") == "clarifying_question"
            and n.get("hunt_id") == hunt_id
        ]
        if matching:
            break

    assert matching, (
        f"clarifying_question notification not seen for hunt={hunt_id}; "
        f"all notifs={[(n.get('kind'), n.get('hunt_id')) for n in notifications]}"
    )

    budget_approval_id = matching[0]["approval_request_id"]
    assert budget_approval_id, "notification missing approval_request_id"

    # ---- Step 3: resolve the budget approval ----
    resp = fastapi_client.post(
        f"/api/approvals/{budget_approval_id}",
        json={"decision": "approve", "feedback": {"budget": 250}},
        headers=authed_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    # ---- Step 4: wait for the listings_found notification ----
    pick_matches: list[dict] = []
    for _ in range(80):  # up to ~8s — discovery + valuation per listing
        time.sleep(0.1)
        resp = fastapi_client.get(
            "/api/notifications", headers=authed_headers
        )
        all_notifs = resp.json()
        pick_matches = [
            n
            for n in all_notifs
            if n.get("kind") == "listings_found"
            and n.get("hunt_id") == hunt_id
        ]
        if pick_matches:
            break

    assert pick_matches, (
        f"listings_found notification not seen for hunt={hunt_id}; "
        f"all kinds={[n.get('kind') for n in all_notifs]}"
    )

    # ---- Step 5: GET /api/hunts/{hunt_id} reports awaiting_picks or negotiating ----
    resp = fastapi_client.get(
        f"/api/hunts/{hunt_id}", headers=authed_headers,
    )
    assert resp.status_code == 200, resp.text
    hunt_state = resp.json()
    assert hunt_state["id"] == hunt_id
    assert hunt_state["budget"] == 250.0
    # Streaming discovery: the hunt can be in ``discovering`` (loop
    # still iterating across marketplaces), ``awaiting_picks`` (loop
    # finished), or ``negotiating`` (the test already spawned a job
    # via the new POST endpoint).
    assert hunt_state["status"] in (
        "discovering",
        "awaiting_picks",
        "negotiating",
    ), hunt_state

    # ---- Step 6: spawn a negotiation on a streamed candidate ----
    # The hunt lifecycle no longer pauses on a global picker; instead
    # the user POSTs to ``/api/hunts/{hunt_id}/jobs`` with any
    # surfaced listing id whenever they're ready to negotiate.
    #
    # Wait for the streaming discovery to settle before issuing the
    # POST — with the in-memory SQLite test DB, concurrent commits
    # from the discovery loop + the API endpoint can clash on
    # ``COMMIT``. In production (Postgres) each connection is
    # independent and this race doesn't happen.
    for _ in range(40):
        time.sleep(0.1)
        resp = fastapi_client.get(
            f"/api/hunts/{hunt_id}", headers=authed_headers,
        )
        if resp.json().get("status") in ("awaiting_picks", "closed"):
            break

    listing_id = pick_matches[0]["payload"]["listing"]["id"]
    resp = fastapi_client.post(
        f"/api/hunts/{hunt_id}/jobs",
        json={"listing_id": listing_id},
        headers=authed_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["job_id"]
    assert body["created"] is True

    # Hunt should now report ``negotiating`` (the new POST endpoint
    # flips it as soon as the first job spawns).
    final = fastapi_client.get(
        f"/api/hunts/{hunt_id}", headers=authed_headers,
    ).json()
    assert final["status"] in ("negotiating", "closed"), final


def test_acceptance_criteria_imports():
    """AC #4 verbatim — import smoke test."""
    from api.orchestration.hunts import start_hunt, run_hunt_lifecycle  # noqa: F401
    print("ok")


def test_acceptance_criteria_shared_agent():
    """AC #5 verbatim — picker and clarifier share the same Agent."""
    from api.agents.picker import app as a
    from api.agents.clarifier import app as b
    assert a is b


def test_acceptance_criteria_hunt_table():
    """AC #2 verbatim — Hunt.__tablename__."""
    from api.models import Hunt
    assert Hunt.__tablename__ == "hunts"


def test_acceptance_criteria_job_has_hunt_id():
    """AC #3 verbatim — Job carries hunt_id column."""
    from api.models import Job
    cols = [c.name for c in Job.__table__.columns]
    assert "hunt_id" in cols


def test_alembic_0003_chains_off_0002():
    """AC #8 — 0003 has down_revision = '0002'.

    ``alembic.op`` is only importable inside a live alembic context, so
    we can't ``exec_module`` the migration file in a unit test — read it
    as text and parse the revision metadata directly.
    """
    from pathlib import Path
    import re

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "0003_hunts_table.py"
    )
    text = path.read_text()
    rev_match = re.search(r'revision\s*:\s*str\s*=\s*"([^"]+)"', text)
    down_match = re.search(
        r'down_revision\s*:\s*Union\[str,\s*None\]\s*=\s*"([^"]+)"', text
    )
    assert rev_match is not None and rev_match.group(1) == "0003"
    assert down_match is not None and down_match.group(1) == "0002"
