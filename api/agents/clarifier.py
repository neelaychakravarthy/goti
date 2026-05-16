"""AgentField reasoner: ask one budget clarifying question.

Run as a sidecar process:

    python -m api.agents.clarifier

It registers with the AgentField control plane at `AF_CONTROL_PLANE_URL` and
listens for invocations. The FastAPI `POST /api/goals` route forwards to this
reasoner via HTTP.
"""

from __future__ import annotations

import asyncio
import logging

from api.agents._af_app import app
from api.llm import draft_clarifying_question

logger = logging.getLogger(__name__)


@app.reasoner()
async def ask_clarifying_question(goal: str) -> dict:
    """Return one budget-related clarifying question for the user's goal."""
    logger.info("clarifier: received goal=%r", goal)
    try:
        question = await draft_clarifying_question(goal)
    except Exception as exc:  # noqa: BLE001 — surface to caller with detail
        logger.exception("clarifier: LLM draft failed")
        return {"error": f"clarifying_question_draft_failed: {exc!s}"}
    logger.info("clarifier: drafted question=%r", question)
    return {"clarifying_question": question}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("clarifier: starting AgentField reasoner; registering with control plane.")
    # AgentField's `app.run()` is the documented registration call. It may
    # block forever (control-plane long-poll) — that's expected for a sidecar.
    try:
        app.run()
    except RuntimeError:
        # Some agentfield builds expose an async runner — fall back to that.
        asyncio.run(app.run_async())  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
