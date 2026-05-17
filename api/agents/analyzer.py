"""AgentField reasoner: post-close negotiation analyzer.

Phase G' of the ancient-brewing-brooks chat-first plan. After a deal
closes (winner OR sibling decline), ``run_post_close_analysis`` fires
one ``analyze_negotiation`` invocation per closed job in parallel. Each
invocation:

1. Hands the full transcript + listing + outcome + price context to the
   LLM via ``analyze_full_negotiation`` (``api/llm.py``).
2. Returns a structured ``{what_worked, what_didnt, key_moments,
   tactical_lessons, category, region, confidence}`` dict.

The orchestration layer (``api/orchestration/analyzer.py``) writes the
analysis as ONE assistant-role message to EverOS via
``client.v1.memories.agent.add(content=json.dumps(analysis))`` and then
flushes for server-side Skill extraction.

This is purely the LLM-driven analyzer reasoner — no ``app.pause()``,
no HITL. Falls back to a safe default on any LLM failure so the
post-close flow never crashes.
"""

from __future__ import annotations

import logging

from api.agents._af_app import app
from api.llm import analyze_full_negotiation

logger = logging.getLogger(__name__)


@app.reasoner()
async def analyze_negotiation(
    negotiation_transcript: list[dict],
    listing: dict,
    outcome: str,
    target_price: float | None = None,
    final_price: float | None = None,
    hunt_goal: str = "",
    user_id: str = "",
) -> dict:
    """Produce a structured post-close analysis of one negotiation.

    Args:
        negotiation_transcript: full message thread for this job, as
            ``[{role, text, sent_at}, ...]``. Roles are the internal
            ``buyer_agent`` / ``seller`` / ``system`` set.
        listing: the listing dict (id, title, marketplace, price,
            description, url, etc.).
        outcome: ``"closed_deal"`` for the winner job, ``"declined"``
            for sibling jobs, ``"no_response"`` when no seller reply
            ever came in, ``"abandoned"`` otherwise.
        target_price: the buyer's pre-negotiation target.
        final_price: actual agreed price (winner only; None for siblings).
        hunt_goal: the hunt's natural-language goal text — context for
            "category" inference.
        user_id: tenant id (forwarded but not currently consumed).

    Returns:
        ``{what_worked: [str], what_didnt: [str],
            key_moments: [{turn_idx, observation}],
            tactical_lessons: [str], category: str, region: str,
            confidence: float}``
    """
    logger.info(
        "analyzer: analyzing job listing=%s outcome=%s msgs=%d",
        listing.get("id") if isinstance(listing, dict) else "?",
        outcome,
        len(negotiation_transcript) if isinstance(negotiation_transcript, list) else 0,
    )
    try:
        analysis = await analyze_full_negotiation(
            negotiation_transcript=negotiation_transcript or [],
            listing=listing or {},
            outcome=outcome,
            target_price=target_price,
            final_price=final_price,
            hunt_goal=hunt_goal,
        )
    except Exception as exc:  # noqa: BLE001 — graceful degrade
        logger.exception("analyzer: analyze_full_negotiation raised; using fallback")
        return _fallback_analysis(outcome=outcome, error=str(exc))

    # Defensive coercion — the LLM might omit fields.
    if not isinstance(analysis, dict):
        return _fallback_analysis(outcome=outcome, error="llm returned non-dict")
    return _coerce_analysis(analysis, outcome=outcome)


def _fallback_analysis(*, outcome: str, error: str | None = None) -> dict:
    base = {
        "what_worked": [],
        "what_didnt": [],
        "key_moments": [],
        "tactical_lessons": [],
        "category": "",
        "region": "",
        "confidence": 0.0,
    }
    if error:
        base["error"] = error
    base["outcome"] = outcome
    return base


def _coerce_analysis(analysis: dict, *, outcome: str) -> dict:
    """Coerce LLM-shaped output to the expected analyzer contract."""

    def _str_list(value) -> list[str]:  # noqa: ANN001 — defensive coerce
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    out.append(stripped)
        return out

    def _moments(value) -> list[dict]:  # noqa: ANN001 — defensive coerce
        if not isinstance(value, list):
            return []
        out: list[dict] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            turn_raw = item.get("turn_idx")
            try:
                turn_idx = int(turn_raw) if turn_raw is not None else 0
            except (TypeError, ValueError):
                turn_idx = 0
            observation = item.get("observation")
            if not isinstance(observation, str) or not observation.strip():
                continue
            out.append({"turn_idx": turn_idx, "observation": observation.strip()})
        return out

    confidence = analysis.get("confidence")
    if isinstance(confidence, (int, float)):
        confidence = float(confidence)
    elif isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except ValueError:
            confidence = 0.0
    else:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "what_worked": _str_list(analysis.get("what_worked")),
        "what_didnt": _str_list(analysis.get("what_didnt")),
        "key_moments": _moments(analysis.get("key_moments")),
        "tactical_lessons": _str_list(analysis.get("tactical_lessons")),
        "category": str(analysis.get("category") or "").strip(),
        "region": str(analysis.get("region") or "").strip(),
        "confidence": confidence,
        "outcome": outcome,
    }
