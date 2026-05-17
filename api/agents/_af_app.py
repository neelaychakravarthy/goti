"""Shared AgentField `Agent()` bootstrap.

Every reasoner imports `app` from here and registers itself with
`@app.reasoner()`. All five reasoners (clarifier, valuation,
negotiator, coordinator, picker) share the same `Agent` instance so
they share `app.memory` (the BATNA state bus) and so the control plane
sees a single `goti` node hosting multiple reasoner methods.

We deliberately do NOT call `app.ai(...)` from inside reasoners — LLM
calls happen via `api.llm` (Anthropic SDK directly). AgentField is used
here for its topology + decorator + control-plane primitives only
(incl. `app.memory` for cross-negotiation state and `app.pause()` for
the HITL approval gate).

Shared memory contract (BATNA state bus):

| Key                       | Value                                              | Owner                            |
|---------------------------|----------------------------------------------------|----------------------------------|
| `user_budget:{user_id}`   | float (from clarification)                         | clarifier writes, valuation reads |
| `batna:{user_id}`         | dict[job_id, {current_offer, target_price, status}] | coordinator writes, negotiator reads |
| `job:{job_id}:state`      | dict mirror of DB job state (fast agent access)    | coordinator + negotiator write   |

Verified against agentfield 0.1.84:
- ``app.memory.get(key, default=None) -> Any`` is async.
- ``app.memory.set(key, data) -> None`` is async.
- ``app.pause(approval_request_id, approval_request_url='', ...)`` is async
  and returns an ``agentfield.client.ApprovalResult`` dataclass.

If the docker-compose build pins a different agentfield version with a
diverging API, adjust the reasoners' awaits / unwrap logic accordingly.
"""

from __future__ import annotations

import logging

from api.config import get_settings

logger = logging.getLogger(__name__)


def _build_app():  # noqa: ANN202 — agentfield types may not be available locally
    from agentfield import Agent, AIConfig  # type: ignore

    settings = get_settings()
    # ai_config is required by the AgentField API even though we won't call
    # `app.ai()` from our reasoners — we call Anthropic directly through
    # `api.llm`.
    #
    # ``agentfield_server`` is the URL the SDK uses for its internal
    # control-plane chatter (memory-events WebSocket, request-approval,
    # heartbeats). It DEFAULTS to ``http://localhost:8080`` — but in our
    # setup :8080 is the AGENT'S OWN server, not the control plane. The
    # control plane is FastAPI on :8000 (see ``api/routes/agent_bridge.py``).
    # Point it explicitly at FastAPI so the memory-events handshake
    # reaches our no-op handler instead of 403-ing against the agent
    # server's own route table.
    return Agent(
        node_id="goti",
        ai_config=AIConfig(model=settings.claude_model_id),
        agentfield_server=settings.af_control_plane_url,
    )


app = _build_app()
