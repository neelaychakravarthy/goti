"""Shared AgentField `Agent()` bootstrap.

Every reasoner imports `app` from here and registers itself with
`@app.reasoner()`. All four reasoners (clarifier, valuation, negotiator,
coordinator) share the same `Agent` instance so they share `app.memory`
(the BATNA state bus per SPEC.md) and so the control plane sees a single
`goti` node hosting multiple reasoner methods.

NB: per the plan's mechanical assumption (and SPEC.md "every model call
goes through TokenRouter"), we deliberately do NOT call `app.ai(...)` from
inside reasoners — LLM calls happen via `api.llm` (openai SDK pointed at
TokenRouter). AgentField is used here for its topology + decorator +
control-plane primitives only (incl. `app.memory` for cross-negotiation
state and `app.pause()` for the HITL approval gate).

Shared memory contract (BATNA state bus — see SPEC.md "shared memory"):

| Key                       | Value                                              | Owner                            |
|---------------------------|----------------------------------------------------|----------------------------------|
| `user_budget:{user_id}`   | float (from clarification)                         | clarifier writes, valuation reads |
| `batna:{user_id}`         | dict[job_id, {current_offer, target_price, status}] | coordinator writes, negotiator reads |
| `job:{job_id}:state`      | dict mirror of DB job state (fast agent access)    | coordinator + negotiator write   |

Verified against agentfield 0.1.84 during Pass 1:
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
    # `app.ai()` from our reasoners — we route through TokenRouter manually.
    return Agent(
        node_id="goti",
        ai_config=AIConfig(model=settings.glm_model_id),
    )


app = _build_app()
