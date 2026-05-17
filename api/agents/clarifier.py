"""AgentField reasoner: ask one budget clarifying question + pause for the answer.

Run as a sidecar process:

    python -m api.agents.clarifier

It registers with the AgentField control plane at `AF_CONTROL_PLANE_URL` and
listens for invocations. The hunt lifecycle (``api/orchestration/hunts.py``)
invokes this reasoner with ``goal`` + ``hunt_id`` + ``user_id``; the
reasoner drafts the clarifying question (via Anthropic Claude), then
calls ``app.pause()`` so the user can submit their budget answer. The
bridge router (``api/routes/agent_bridge.py``) turns the pause into a
``clarifying_question`` notification + DB-backed approval row; the user
POSTs to ``/api/approvals/{id}`` with ``{decision: "approve",
feedback: {budget: <number>}}``; the future resumes with the budget.
"""

from __future__ import annotations

import logging

from api.agents._af_app import app
from api.llm import draft_clarifying_question

logger = logging.getLogger(__name__)


@app.reasoner()
async def ask_clarifying_question(
    goal: str,
    hunt_id: str = "",
    user_id: str = "",
) -> dict:
    """Draft a budget-related clarifying question + pause for the user's answer.

    Returns ``{"budget": <number-or-null>, "clarifying_question": <str>,
    "approval_status": <decision>}`` once the pause resolves.

    Legacy single-shot mode: if ``hunt_id`` is empty (the no-hunt-context
    ``POST /api/goals`` flow that only wants the question text), the
    reasoner returns the question immediately without pausing. The hunt
    lifecycle always supplies ``hunt_id``.
    """
    logger.info("clarifier: received goal=%r hunt=%r", goal, hunt_id)
    try:
        question = await draft_clarifying_question(goal)
    except Exception as exc:  # noqa: BLE001 — surface to caller with detail
        logger.exception("clarifier: LLM draft failed")
        return {"error": f"clarifying_question_draft_failed: {exc!s}"}
    logger.info("clarifier: drafted question=%r", question)

    # Legacy / no-hunt-context invocation: just return the question.
    if not hunt_id:
        return {"clarifying_question": question}

    approval_request_id = f"hunt-{hunt_id}-budget"
    approval_request_url = f"http://localhost:8000/api/hunts/{hunt_id}"

    payload = {
        "kind": "clarifying_question",
        "title": "What's your budget?",
        "body": question,
        "hunt_id": hunt_id,
        "user_id": user_id,
        "target_href": f"/start?hunt_id={hunt_id}&q=budget",
        "question": question,
    }

    try:
        result = await app.pause(
            approval_request_id=approval_request_id,
            approval_request_url=approval_request_url,
            payload=payload,
        )
    except TypeError:
        # Some AgentField versions don't accept ``payload`` on pause(); fall
        # back to the minimal call (the bridge upserts a row from
        # request-approval anyway).
        try:
            result = await app.pause(
                approval_request_id=approval_request_id,
                approval_request_url=approval_request_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("clarifier: app.pause() raised")
            return {
                "clarifying_question": question,
                "budget": None,
                "approval_status": "pause_failed",
                "error": str(exc),
            }
    except Exception as exc:  # noqa: BLE001
        logger.exception("clarifier: app.pause() raised")
        return {
            "clarifying_question": question,
            "budget": None,
            "approval_status": "pause_failed",
            "error": str(exc),
        }

    feedback = _extract_feedback(result)
    budget = _coerce_budget(feedback)
    decision = _extract_decision(result)
    return {
        "clarifying_question": question,
        "budget": budget,
        "approval_status": decision,
    }


def _extract_feedback(result):  # noqa: ANN001
    if isinstance(result, dict):
        return result.get("feedback") or result.get("response")
    return getattr(result, "feedback", None) or getattr(result, "response", None)


def _extract_decision(result) -> str:  # noqa: ANN001
    if isinstance(result, dict):
        raw = result.get("decision", "approved")
    else:
        raw = getattr(result, "decision", "approved")
    raw = str(raw).lower()
    if raw in ("approve", "approved"):
        return "approved"
    if raw in ("reject", "rejected"):
        return "rejected"
    return raw


def _coerce_budget(feedback):  # noqa: ANN001 — feedback can be int/float/str/dict
    """Extract a numeric budget from feedback.

    Accepts:
    - ``{"budget": 250}`` / ``{"answer": "250"}`` / ``{"value": 250}``
    - ``250`` / ``"$250"``
    - any unparseable shape -> None.
    """
    if feedback is None:
        return None
    if isinstance(feedback, dict):
        candidate = (
            feedback.get("budget")
            or feedback.get("answer")
            or feedback.get("value")
        )
    else:
        candidate = feedback
    if isinstance(candidate, (int, float)):
        return float(candidate)
    if isinstance(candidate, str):
        cleaned = candidate.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def main() -> None:
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # IMPORTANT: import every sibling reasoner module BEFORE ``app.run()`` so
    # their ``@app.reasoner()`` decorators fire and the agent server publishes
    # the complete method set (assess_listing, draft_message, spawn_negotiations,
    # pick_listings, classify_negotiation_state, analyze_negotiation). Without
    # these imports, the agent only serves ``ask_clarifying_question`` and
    # other reasoner calls 404.
    from api.agents import (  # noqa: F401 — side-effect imports
        analyzer,
        classifier,
        coordinator,
        negotiator,
        picker,
        valuation,
    )

    logger.info(
        "clarifier: starting AgentField agent server on :8080 with reasoners="
        "[ask_clarifying_question, assess_listing, draft_message, "
        "spawn_negotiations, pick_listings, classify_negotiation_state, "
        "analyze_negotiation]."
    )
    # AgentField's `app.run()` auto-detects CLI vs server mode and starts the
    # agent's own FastAPI server (via Agent.serve). We pin port=8080 so
    # FastAPI can reach it at a known address.
    app.run(port=8080, host="0.0.0.0")


if __name__ == "__main__":
    main()
