"""TestClient sweep for the AgentField control-plane bridge.

Verifies the full pause/resume bridge:

1. ``POST /api/v1/agents/{node}/executions/{id}/request-approval`` creates
   an ``ApprovalQueueItem`` + linked ``Notification`` and pushes onto the
   in-memory queue.
2. ``GET /api/notifications`` returns the unread notification.
3. ``POST /api/approvals/{approval_request_id}`` resolves the queue row,
   marks the notification resolved, and attempts the agent-webhook POST
   (failure swallowed silently — see ``api/routes/approvals.py``).
4. ``GET /api/notifications/stream`` returns ``text/event-stream`` and
   emits the first event within budget.

The shared ``conftest.py`` flips ``POSTGRES_URI`` to an in-memory
SQLite + registers cross-dialect DDL adapters so the Postgres-typed
``UUID`` / ``JSONB`` columns render correctly without a live Postgres.

Pass-7 update: tests that hit user-protected routes use the
``stub_verify_token`` fixture from ``conftest.py`` + the synthetic
``test-token`` bearer header. The bridge / notifications routes
themselves don't require auth, so most tests in this file don't need
the stub.
"""

from __future__ import annotations

import asyncio
import time

import pytest

# Postgres-only ``alembic upgrade head`` would fail at lifespan startup;
# patch the migration runner to a no-op so the test stack can use SQLite.
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
    from fastapi.testclient import TestClient  # noqa: PLC0415

    with TestClient(app) as c:
        yield c


def test_request_approval_creates_queue_row_and_notification(client):
    """AC 9.1: bridge ingest path."""
    response = client.post(
        "/api/v1/agents/goti/executions/exec-123/request-approval",
        json={
            "approval_request_id": "req-1",
            "callback_url": "http://localhost:8080/webhooks/approval",
            "expires_in_hours": 72,
            "payload": {
                "kind": "clarifying_question",
                "question": "What's your budget?",
                "user_id": "demo_user",
            },
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["approval_request_id"] == "req-1"

    from api.db import AsyncSessionLocal  # noqa: PLC0415
    from api.models import ApprovalQueueItem, Notification  # noqa: PLC0415

    async def _check_rows():
        async with AsyncSessionLocal() as session:
            queue = await ApprovalQueueItem.get_by_approval_request_id(session, "req-1")
            notif = await Notification.get_by_approval_request_id(session, "req-1")
            return queue, notif

    queue, notif = asyncio.run(_check_rows())
    assert queue is not None
    assert queue.execution_id == "exec-123"
    assert queue.agent_node_id == "goti"
    assert queue.agent_callback_url == "http://localhost:8080/webhooks/approval"
    assert notif is not None
    assert notif.user_id == "demo_user"
    assert notif.kind == "clarifying_question"
    assert "budget" in notif.body.lower()


def test_list_notifications_returns_unread(client, stub_verify_token, authed_headers):
    """AC 9.2: list endpoint surfaces the unread notification.

    Bootstraps the auth-stubbed user (so the notification user_id matches
    the authed user UUID), then sends a new bridge request-approval that
    references that user, then asserts the list endpoint returns it.
    """
    # Bootstrap the user row + read back its uuid.
    response = client.get("/api/me", headers=authed_headers)
    assert response.status_code == 200, response.text
    user_id = response.json()["id"]

    # Bridge a fresh notification with the user_id matching the authed user.
    bridge_resp = client.post(
        "/api/v1/agents/goti/executions/exec-list-test/request-approval",
        json={
            "approval_request_id": "req-list-test",
            "callback_url": "http://localhost:8080/webhooks/approval",
            "payload": {
                "kind": "clarifying_question",
                "question": "What's your budget?",
                "user_id": user_id,
            },
        },
    )
    assert bridge_resp.status_code == 200, bridge_resp.text

    list_resp = client.get("/api/notifications", headers=authed_headers)
    assert list_resp.status_code == 200
    notifications = list_resp.json()
    matching = [n for n in notifications if n["approval_request_id"] == "req-list-test"]
    assert matching, (
        f"req-list-test not found; got {[n['approval_request_id'] for n in notifications]}"
    )
    assert matching[0]["status"] == "unread"


def test_approve_resolves_queue_and_notification(client, stub_verify_token, authed_headers):
    """AC 9.3: approval lifecycle. Requires auth (POST /api/approvals/{id})."""
    response = client.post(
        "/api/approvals/req-1",
        json={"decision": "approve", "feedback": 250},
        headers=authed_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["matched_row"] is True
    assert data["decision"] == "approve"

    from api.db import AsyncSessionLocal  # noqa: PLC0415
    from api.models import ApprovalQueueItem, Notification  # noqa: PLC0415

    async def _check_resolved():
        async with AsyncSessionLocal() as session:
            queue = await ApprovalQueueItem.get_by_approval_request_id(session, "req-1")
            notif = await Notification.get_by_approval_request_id(session, "req-1")
            return queue, notif

    queue, notif = asyncio.run(_check_resolved())
    assert queue.decision == "approve"
    assert queue.decided_at is not None
    assert notif.status == "resolved"
    assert notif.resolved_at is not None


def test_sse_stream_emits_event_within_budget(stub_verify_token, authed_headers):
    """AC 9.4: SSE stream returns text/event-stream + first event within 5s.

    Uses direct ASGI invocation rather than TestClient.stream() because
    the latter blocks waiting for the full response body even when the
    generator produces incremental events. The ASGI ``send`` callback
    receives each ``http.response.body`` chunk as the generator yields,
    matching the live behaviour an SSE client sees.

    Pass-7 update: the SSE endpoint is auth-gated. EventSource can't
    set headers, so the token is passed via ``?token=...``. We pass
    ``Authorization`` here for the bootstrap + the synthetic test
    token via the query string for the SSE scope.
    """
    from fastapi.testclient import TestClient  # noqa: PLC0415

    with TestClient(app) as c:
        # Bootstrap the user via the auth stub.
        r = c.get("/api/me", headers=authed_headers)
        assert r.status_code == 200
        user_id = r.json()["id"]

        # Seed a notification first so the snapshot has content (also confirms
        # the snapshot emission path, not just the per-tick ping).
        c.post(
            "/api/v1/agents/goti/executions/exec-sse/request-approval",
            json={
                "approval_request_id": "req-sse",
                "callback_url": "http://localhost:8080/webhooks/approval",
                "payload": {
                    "kind": "approval_needed",
                    "draft_text": "Hello, is this still available?",
                    "user_id": user_id,
                },
            },
        )

    received: list[dict] = []
    sent_request_once = [False]

    async def _receive():
        if sent_request_once[0]:
            # Block "forever" so we don't disconnect before the generator
            # produces its first event.
            await asyncio.sleep(60)
            return {"type": "http.disconnect"}
        sent_request_once[0] = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _send(message):
        received.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/notifications/stream",
        "raw_path": b"/api/notifications/stream",
        "query_string": b"token=test-token",
        "headers": [],
        "server": ("test", 80),
        "client": ("test", 1234),
        "scheme": "http",
        "root_path": "",
    }

    async def _run():
        try:
            await asyncio.wait_for(app(scope, _receive, _send), timeout=1.0)
        except asyncio.TimeoutError:
            pass

    start = time.time()
    asyncio.run(_run())
    elapsed = time.time() - start
    assert elapsed < 2.0, f"SSE stream took {elapsed:.2f}s to emit first event"

    # Find the response-start + at least one body chunk.
    starts = [m for m in received if m.get("type") == "http.response.start"]
    bodies = [m for m in received if m.get("type") == "http.response.body"]
    assert starts, f"no response.start observed; got: {[m.get('type') for m in received]}"
    headers = dict(starts[0]["headers"])
    assert b"text/event-stream" in headers.get(b"content-type", b""), headers
    assert bodies, "no body chunks observed within 1s"
    first_body = bodies[0]["body"].decode("utf-8", errors="replace")
    assert "event:" in first_body
    assert "data:" in first_body


def test_unknown_approval_id_returns_idempotent_ok(stub_verify_token, authed_headers):
    """Synthetic fixture ids (no DB row) return ok=true with matched_row=False."""
    from fastapi.testclient import TestClient  # noqa: PLC0415

    with TestClient(app) as c:
        response = c.post(
            "/api/approvals/ap-unknown-fixture",
            json={"decision": "approve"},
            headers=authed_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["matched_row"] is False


def test_request_approval_idempotent_on_retry():
    """Same approval_request_id twice yields a single queue+notification row."""
    from fastapi.testclient import TestClient  # noqa: PLC0415

    body = {
        "approval_request_id": "req-idempotent",
        "callback_url": "http://localhost:8080/webhooks/approval",
        "payload": {
            "kind": "approval_needed",
            "draft_text": "Initial draft",
            "user_id": "demo_user",
        },
    }
    with TestClient(app) as c:
        r1 = c.post(
            "/api/v1/agents/goti/executions/exec-x/request-approval",
            json=body,
        )
        r2 = c.post(
            "/api/v1/agents/goti/executions/exec-x/request-approval",
            json=body,
        )
    assert r1.status_code == 200
    assert r2.status_code == 200

    from sqlalchemy import select  # noqa: PLC0415

    from api.db import AsyncSessionLocal  # noqa: PLC0415
    from api.models import ApprovalQueueItem, Notification  # noqa: PLC0415

    async def _count_rows():
        async with AsyncSessionLocal() as session:
            queue_q = await session.execute(
                select(ApprovalQueueItem).where(
                    ApprovalQueueItem.approval_request_id == "req-idempotent"
                )
            )
            notif_q = await session.execute(
                select(Notification).where(
                    Notification.approval_request_id == "req-idempotent"
                )
            )
            return len(list(queue_q.scalars().all())), len(
                list(notif_q.scalars().all())
            )

    queue_count, notif_count = asyncio.run(_count_rows())
    assert queue_count == 1
    assert notif_count == 1
