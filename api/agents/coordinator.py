"""AgentField reasoner: seed the BATNA state bus + return job IDs to spawn.

Shares `app` (and therefore `app.memory`) with the other three reasoners —
see `_af_app.py`. Invoked from FastAPI (Pass 2) when the user clicks
"negotiate" on one or more listings after the clarification step. The
reasoner seeds `app.memory[f"batna:{user_id}"]` with placeholder entries
for each new job so the negotiator reasoners can read cross-negotiation
state when drafting messages.

Actual job-row creation + reasoner dispatch happens in FastAPI (Pass 2)
which consumes this reasoner's return value.

`app.memory.get` / `app.memory.set` confirmed async against agentfield
0.1.84 in Pass-1 verification. See `_af_app.py` docstring for the full
shared-memory contract.
"""

from __future__ import annotations

import logging

from api.agents._af_app import app

logger = logging.getLogger(__name__)


@app.reasoner()
async def spawn_negotiations(
    goal_id: str,
    listings: list[dict],  # noqa: ARG001 — accepted for context; Pass 2 may use it
    target_listing_ids: list[str],
    target_price: float,
    user_id: str = "demo_user",
) -> dict:
    """Seed BATNA state for the about-to-be-spawned negotiation jobs.

    For each ``listing_id`` the user picked, build a deterministic
    ``job_id = f"job-{goal_id}-{listing_id}"`` and write a placeholder
    BATNA entry to shared memory under ``batna:{user_id}``. Existing entries
    in the user's BATNA map are preserved (in case earlier negotiations are
    still active).

    Returns ``{job_ids, status, batna_seed}``. FastAPI (Pass 2) consumes
    this to create Job rows + dispatch negotiator reasoners.
    """
    batna_seed: dict[str, dict] = {}
    job_ids: list[str] = []
    for listing_id in target_listing_ids:
        job_id = f"job-{goal_id}-{listing_id}"
        job_ids.append(job_id)
        batna_seed[job_id] = {
            "listing_id": listing_id,
            "current_offer": None,
            "target_price": target_price,
            "status": "spawning",
        }

    try:
        existing = await app.memory.get(f"batna:{user_id}")
    except Exception:  # noqa: BLE001 — memory backend may be unavailable in dev
        logger.exception("coordinator: app.memory.get failed; seeding without prior state.")
        existing = None
    if not isinstance(existing, dict):
        existing = {}
    existing.update(batna_seed)

    try:
        await app.memory.set(f"batna:{user_id}", existing)
    except Exception:  # noqa: BLE001
        logger.exception("coordinator: app.memory.set failed; returning seed without persistence.")

    logger.info(
        "coordinator: seeded %d jobs for user=%s goal=%s", len(job_ids), user_id, goal_id
    )
    return {
        "job_ids": job_ids,
        "status": "ready_to_spawn",
        "batna_seed": batna_seed,
    }
