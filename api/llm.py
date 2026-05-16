"""TokenRouter LLM gateway.

SPEC.md: "every model call goes through TokenRouter." This module is the
single chokepoint — every other module that needs an LLM call imports from
here. Uses the official `openai` SDK pointed at TokenRouter's OpenAI-compatible
endpoint.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from api.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.tokenrouter_api_key:
        logger.warning(
            "TOKENROUTER_API_KEY not set; LLM calls will fail. "
            "Set the env var in .env before invoking /api/goals."
        )
    return AsyncOpenAI(
        api_key=settings.tokenrouter_api_key or "missing-key",
        base_url=settings.tokenrouter_base_url,
    )


_CLARIFIER_SYSTEM_PROMPT = (
    "You help a user shop for an item. The user has just stated a goal. "
    "Respond with exactly ONE short clarifying question about their budget. "
    "Keep it to a single sentence under 25 words. Do not greet, do not "
    "summarize the goal — just ask the budget question."
)


_VALUATION_SYSTEM_PROMPT = (
    "You're a deal-hunting valuation analyst. Given a listing and the buyer's "
    "budget, return a JSON object with these fields:\n"
    "  - fair_price_estimate (number): your estimate of what the item is "
    "actually worth on the secondhand market.\n"
    "  - walk_away_price (number): the absolute maximum the buyer should pay; "
    "above this, walk.\n"
    "  - target_price (number): the opening counter-offer the buyer should "
    "anchor with; typically 10-20% below fair_price_estimate.\n"
    "  - reasoning (string): 1-2 sentences explaining the numbers.\n"
    "Output ONLY valid JSON. No prose, no markdown fences."
)


_NEGOTIATION_SYSTEM_PROMPT = (
    "You're a deal-hunting negotiator. Draft the next buyer-side message in a "
    "marketplace negotiation. Use BATNA leverage from the buyer's other active "
    "negotiations (`batna_state`) when relevant — for example, mention "
    "competing offers ('I have another seller at $X — can you match?'). Keep "
    "the message polite, concise, and natural; do not sound like a bot. Return "
    "a JSON object with:\n"
    "  - draft_text (string): the message to send.\n"
    "  - draft_reasoning (string): 1-2 sentences explaining why this draft "
    "(esp. any BATNA leverage used).\n"
    "Output ONLY valid JSON. No prose, no markdown fences."
)


async def draft_clarifying_question(goal: str) -> str:
    """Ask GLM-5.1 (via TokenRouter) for one budget-related clarifying question.

    Raises on TokenRouter / model errors. Callers should catch and surface a
    clear HTTP error.
    """
    settings = get_settings()
    client = get_client()
    logger.info(
        "Calling TokenRouter at %s with model=%s", settings.tokenrouter_base_url, settings.glm_model_id
    )
    completion = await client.chat.completions.create(
        model=settings.glm_model_id,
        messages=[
            {"role": "system", "content": _CLARIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": goal},
        ],
        temperature=0.4,
        max_tokens=120,
    )
    content = (completion.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("TokenRouter returned an empty completion.")
    return content


def _parse_json_fallback(raw: str, fallback: dict) -> dict:
    """Parse a JSON object from an LLM response; return `fallback` on failure.

    LLMs sometimes wrap JSON in markdown fences or add a stray prefix. Try a
    few rescues before giving up.
    """
    if not raw:
        return fallback
    text = raw.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        # Drop the opening fence (handles ```json and ``` alike).
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Last-ditch: find the first `{` and last `}` and try that slice.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                logger.warning("LLM JSON parse failed; returning fallback. raw=%r", raw[:200])
                return fallback
        else:
            logger.warning("LLM JSON parse failed; returning fallback. raw=%r", raw[:200])
            return fallback
    if not isinstance(parsed, dict):
        logger.warning("LLM returned non-dict JSON; returning fallback. parsed=%r", parsed)
        return fallback
    return parsed


async def _chat_json(system: str, user_payload: dict[str, Any]) -> str:
    """Call the chat completion API with a system + user-as-JSON message.

    Returns the raw assistant text content; callers parse it.
    """
    settings = get_settings()
    client = get_client()
    completion = await client.chat.completions.create(
        model=settings.glm_model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        temperature=0.4,
        max_tokens=400,
    )
    return (completion.choices[0].message.content or "").strip()


async def draft_valuation(listing: dict, budget: float) -> dict:
    """Score a listing's fair price + walk-away + target negotiation price.

    Returns ``{fair_price_estimate, walk_away_price, target_price, reasoning}``.
    On parse / transport error: returns a safe fallback derived from `budget`
    so callers (the valuation reasoner, then Pass 2's routes) never see a
    500. Errors are logged.
    """
    fallback_target = round(float(budget) * 0.85, 2) if budget else 0.0
    fallback_walk = round(float(budget) * 1.0, 2) if budget else 0.0
    fallback_fair = round(float(budget) * 0.95, 2) if budget else 0.0
    fallback = {
        "fair_price_estimate": fallback_fair,
        "walk_away_price": fallback_walk,
        "target_price": fallback_target,
        "reasoning": "fallback — LLM call or parse failed; derived from budget.",
    }

    try:
        raw = await _chat_json(
            _VALUATION_SYSTEM_PROMPT,
            {"listing": listing, "buyer_budget": budget},
        )
    except Exception:  # noqa: BLE001
        logger.exception("draft_valuation: TokenRouter call failed; returning fallback.")
        return fallback

    parsed = _parse_json_fallback(raw, fallback)
    # Coerce numeric fields defensively; LLMs sometimes return strings.
    for key in ("fair_price_estimate", "walk_away_price", "target_price"):
        val = parsed.get(key)
        if isinstance(val, (int, float)):
            parsed[key] = float(val)
        elif isinstance(val, str):
            try:
                parsed[key] = float(val.replace("$", "").replace(",", ""))
            except ValueError:
                parsed[key] = fallback[key]
        else:
            parsed[key] = fallback[key]
    if not isinstance(parsed.get("reasoning"), str):
        parsed["reasoning"] = fallback["reasoning"]
    return parsed


async def draft_negotiation(
    conversation: list[dict],
    target_price: float,
    batna_state: dict,
) -> dict:
    """Draft the next outbound negotiation message.

    `batna_state` is the user's OTHER active negotiations
    (``job_id -> {current_offer, target_price, status}``) — the system
    prompt instructs the model to use this as leverage when relevant.

    Returns ``{draft_text, draft_reasoning}``. On parse / transport error:
    returns a minimal safe fallback. Errors are logged but never raised so
    Pass 2's routes don't 500.
    """
    fallback = {
        "draft_text": "Hi, is this still available? Would you consider a slightly lower offer?",
        "draft_reasoning": "fallback — LLM call or parse failed; sending a safe opener.",
    }

    try:
        raw = await _chat_json(
            _NEGOTIATION_SYSTEM_PROMPT,
            {
                "conversation": conversation,
                "target_price": target_price,
                "batna_state": batna_state,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("draft_negotiation: TokenRouter call failed; returning fallback.")
        return fallback

    parsed = _parse_json_fallback(raw, fallback)
    if not isinstance(parsed.get("draft_text"), str) or not parsed["draft_text"].strip():
        parsed["draft_text"] = fallback["draft_text"]
    if not isinstance(parsed.get("draft_reasoning"), str):
        parsed["draft_reasoning"] = fallback["draft_reasoning"]
    return parsed
