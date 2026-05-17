"""LLM client — Anthropic Claude.

Every model call (clarifier, valuation, negotiation drafter) flows through
``get_client()``. The same key + model is also handed to ``browser_use``'s
``ChatAnthropic`` adapter for the discovery / send / fetch browser loop —
see ``api/integrations/browser_agent/client.py``.

Uses the official ``anthropic`` SDK directly (``AsyncAnthropic.messages.
create(...)``). Note the shape difference from OpenAI's chat API:
``system`` is a top-level argument, not a message; ``messages`` carries
only ``user`` / ``assistant`` turns; the textual answer lives at
``response.content[0].text``.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from anthropic import AsyncAnthropic

from api.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> AsyncAnthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set; LLM calls will fail. "
            "Set the env var in .env before invoking /api/goals."
        )
    return AsyncAnthropic(api_key=settings.anthropic_api_key or "missing-key")


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
    "marketplace negotiation. The user is running multiple parallel "
    "negotiations for the same item — the full conversation history of every "
    "OTHER active negotiation is provided as `OTHER ACTIVE NEGOTIATIONS` "
    "below. Use them as leverage when helpful — for example, cite a "
    "competing seller's lower price ('I have another seller at $X — can you "
    "match?') or a competing seller's faster pickup window. Make the draft "
    "sound natural and human, not robotic; keep it polite + concise. Return "
    "a JSON object with:\n"
    "  - draft_text (string): the message to send.\n"
    "  - draft_reasoning (string): 1-2 sentences explaining why this draft "
    "(esp. any cross-negotiation leverage used).\n"
    "Output ONLY valid JSON. No prose, no markdown fences."
)


def _render_batna_context(batna_context: list[dict]) -> str:
    """Format the per-negotiation conversation history for the prompt.

    Each entry becomes a labelled block like:

        Negotiation A — Listing "FlexiSpot E7 frame", marketplace=fb,
                        asking=$199, target=$180, status=awaiting_seller_reply
          [you] Hi! Is the desk still available?
          [seller] Yes — going for $199.
          [you] Would you take $180?

    Empty list → empty string (so the prompt naturally falls back to
    "no other negotiations to lean on").
    """
    if not batna_context:
        return ""
    lines: list[str] = ["", "OTHER ACTIVE NEGOTIATIONS FOR THIS HUNT (use as leverage if helpful):", ""]
    for idx, entry in enumerate(batna_context):
        label = chr(ord("A") + idx) if idx < 26 else f"#{idx + 1}"
        title = str(entry.get("listing_title") or "").strip() or "(unknown listing)"
        marketplace = str(entry.get("marketplace") or "").strip() or "?"
        asking = entry.get("asking_price")
        target = entry.get("target_price")
        status = str(entry.get("status") or "").strip() or "?"

        def _fmt_price(p: object) -> str:
            if isinstance(p, (int, float)):
                return f"${int(p)}" if float(p).is_integer() else f"${p}"
            return "?"

        header = (
            f"Negotiation {label} — Listing \"{title}\", marketplace={marketplace}, "
            f"asking={_fmt_price(asking)}, target={_fmt_price(target)}, "
            f"status={status}"
        )
        lines.append(header)
        convo = entry.get("conversation") or []
        if not isinstance(convo, list) or not convo:
            lines.append("  (no messages yet)")
        else:
            for msg in convo:
                if not isinstance(msg, dict):
                    continue
                role = str(msg.get("role") or "").lower()
                # Map internal role names to a human-readable speaker for the
                # prompt. ``buyer_agent`` is the user; ``seller`` the other side.
                speaker = "you" if role in ("buyer_agent", "you") else (
                    "seller" if role == "seller" else role or "?"
                )
                text = str(msg.get("text") or "").strip()
                if not text:
                    continue
                lines.append(f"  [{speaker}] {text}")
        lines.append("")
    return "\n".join(lines)


async def draft_clarifying_question(goal: str) -> str:
    """Ask Claude for one budget-related clarifying question.

    Raises on transport / model errors. Callers should catch and surface
    a clear HTTP error.
    """
    settings = get_settings()
    client = get_client()
    logger.info("Calling Anthropic with model=%s", settings.claude_model_id)
    completion = await client.messages.create(
        model=settings.claude_model_id,
        system=_CLARIFIER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": goal}],
        temperature=0.4,
        max_tokens=120,
    )
    content = _first_text_block(completion).strip()
    if not content:
        raise RuntimeError("Anthropic returned an empty completion.")
    return content


def _first_text_block(completion: Any) -> str:
    """Extract the first text block from an Anthropic Messages response.

    ``messages.create`` returns a ``Message`` whose ``content`` is a list
    of typed blocks (``TextBlock`` / ``ToolUseBlock`` / ...). We only ask
    for text, so the first ``TextBlock`` is the answer — but the API can
    return an empty list if the model refused, so guard for that.
    """
    blocks = getattr(completion, "content", None) or []
    for block in blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text
    return ""


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
    """Call Claude with a system prompt + a JSON-encoded user payload.

    Returns the raw assistant text content; callers parse it.
    """
    settings = get_settings()
    client = get_client()
    completion = await client.messages.create(
        model=settings.claude_model_id,
        system=system,
        messages=[{"role": "user", "content": json.dumps(user_payload)}],
        temperature=0.4,
        max_tokens=400,
    )
    return _first_text_block(completion).strip()


async def draft_valuation(listing: dict, budget: float) -> dict:
    """Score a listing's fair price + walk-away + target negotiation price.

    Returns ``{fair_price_estimate, walk_away_price, target_price, reasoning}``.
    On parse / transport error: returns a safe fallback derived from `budget`
    so callers (the valuation reasoner, then the routes layer) never see a
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
        logger.exception("draft_valuation: Anthropic call failed; returning fallback.")
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


_CLASSIFIER_SYSTEM_PROMPT = (
    "You are an end-of-negotiation classifier. Given the full conversation "
    "between a buyer agent and a seller for a single listing, plus the "
    "buyer's target price, decide whether the negotiation has reached a "
    "natural close-point. A close-point looks like: the seller has agreed "
    "to a price the buyer can live with, or the seller is unmistakably "
    "holding firm at a price the buyer should accept (or walk). Return a "
    "JSON object with:\n"
    "  - ready_to_close (boolean): True if the buyer should now finalize "
    "the deal at the inferred price.\n"
    "  - reason (string): one short sentence explaining the verdict.\n"
    "  - suggested_close_price (number or null): if ready_to_close is True, "
    "the price both sides appear to have agreed on; null otherwise.\n"
    "  - confidence (number between 0 and 1): how sure you are.\n"
    "Be conservative — set ready_to_close=True only when both sides have "
    "signalled they're done negotiating. Output ONLY valid JSON. No prose, "
    "no markdown fences."
)


async def classify_negotiation_state(
    conversation: list[dict],
    listing: dict,
    target_price: float | None,
) -> dict:
    """Classify whether a negotiation has reached its close-point.

    Returns ``{ready_to_close, reason, suggested_close_price, confidence}``.
    On parse / transport error: returns a safe default that DOES NOT flag
    the deal as ready (we'd rather miss a close than false-positive into
    finalize). Errors are logged but never raised.
    """
    fallback = {
        "ready_to_close": False,
        "reason": "fallback — classifier unavailable; default to keep negotiating.",
        "suggested_close_price": None,
        "confidence": 0.0,
    }

    user_payload = {
        "conversation": conversation,
        "listing": listing,
        "target_price": target_price,
    }

    try:
        raw = await _chat_json(_CLASSIFIER_SYSTEM_PROMPT, user_payload)
    except Exception:  # noqa: BLE001
        logger.exception(
            "classify_negotiation_state: Anthropic call failed; returning fallback."
        )
        return fallback

    parsed = _parse_json_fallback(raw, fallback)
    # Coerce defensively — LLMs sometimes return strings for booleans/numbers.
    ready_raw = parsed.get("ready_to_close", False)
    if isinstance(ready_raw, bool):
        ready_to_close = ready_raw
    elif isinstance(ready_raw, str):
        ready_to_close = ready_raw.strip().lower() in ("true", "yes", "1")
    else:
        ready_to_close = bool(ready_raw)

    reason = parsed.get("reason")
    if not isinstance(reason, str):
        reason = fallback["reason"]

    price_raw = parsed.get("suggested_close_price")
    suggested_close_price: float | None
    if isinstance(price_raw, (int, float)):
        suggested_close_price = float(price_raw)
    elif isinstance(price_raw, str):
        try:
            suggested_close_price = float(
                price_raw.replace("$", "").replace(",", "").strip()
            )
        except ValueError:
            suggested_close_price = None
    else:
        suggested_close_price = None

    confidence_raw = parsed.get("confidence", 0.0)
    if isinstance(confidence_raw, (int, float)):
        confidence = float(confidence_raw)
    elif isinstance(confidence_raw, str):
        try:
            confidence = float(confidence_raw)
        except ValueError:
            confidence = 0.0
    else:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "ready_to_close": ready_to_close,
        "reason": reason,
        "suggested_close_price": suggested_close_price,
        "confidence": confidence,
    }


def _render_past_lessons(past_lessons: list[dict]) -> str:
    """Format prior-negotiation analyses into a compact prompt block.

    Each entry is a Case-shaped dict carrying ``what_worked``,
    ``what_didnt``, ``tactical_lessons``, ``category``, ``region``. We
    cap the rendered block at roughly 2k tokens (~8k chars) by
    truncating the iteration when we exceed the budget — the most
    recent lessons land first since the caller orders by recency.

    Returns an empty string when no usable lessons are provided so the
    callsite can naturally omit the prompt block.
    """
    if not past_lessons:
        return ""
    char_budget = 8_000
    header_lines: list[str] = [
        "",
        "PAST LESSONS FROM YOUR PRIOR NEGOTIATIONS ON SIMILAR ITEMS:",
        "",
    ]
    body_lines: list[str] = []
    total_chars = sum(len(s) for s in header_lines)
    for idx, lesson in enumerate(past_lessons):
        if not isinstance(lesson, dict):
            continue
        category = str(lesson.get("category") or "").strip()
        region = str(lesson.get("region") or "").strip()
        outcome = str(lesson.get("outcome") or "").strip()
        worked = [
            str(s).strip()
            for s in (lesson.get("what_worked") or [])
            if isinstance(s, str) and s.strip()
        ]
        didnt = [
            str(s).strip()
            for s in (lesson.get("what_didnt") or [])
            if isinstance(s, str) and s.strip()
        ]
        tactics = [
            str(s).strip()
            for s in (lesson.get("tactical_lessons") or [])
            if isinstance(s, str) and s.strip()
        ]
        if not (worked or didnt or tactics):
            # Nothing meaningful in this lesson — skip the whole block.
            continue
        prefix = f"Prior negotiation {idx + 1}"
        meta_bits = [b for b in (category, region, outcome) if b]
        if meta_bits:
            prefix += " (" + ", ".join(meta_bits) + ")"
        block_lines = [prefix + ":"]
        if worked:
            block_lines.append("  What worked:")
            for w in worked[:5]:
                block_lines.append(f"    - {w}")
        if didnt:
            block_lines.append("  What didn't work:")
            for d in didnt[:5]:
                block_lines.append(f"    - {d}")
        if tactics:
            block_lines.append("  Apply:")
            for t in tactics[:5]:
                block_lines.append(f"    - {t}")
        block_lines.append("")
        block_str = "\n".join(block_lines)
        if total_chars + len(block_str) > char_budget:
            break
        body_lines.extend(block_lines)
        total_chars += len(block_str)
    if not body_lines:
        return ""
    return "\n".join(header_lines + body_lines)


async def draft_negotiation(
    conversation: list[dict],
    target_price: float,
    batna_context: list[dict],
    past_lessons: list[dict] | None = None,
) -> dict:
    """Draft the next outbound negotiation message.

    ``batna_context`` is the FULL conversation history of every other
    active negotiation in the same hunt. Each entry carries
    ``{job_id, listing_title, marketplace, asking_price, target_price,
    status, conversation: [{role, text, sent_at}, ...]}``. The prompt
    renders each as a labelled block (Negotiation A / B / ...) so the
    model can cite specific competing offers as leverage.

    ``past_lessons`` is the list of analyzed Cases from prior closed
    negotiations on similar items, surfaced by
    ``memory_store.list_top_cases_for_draft``. Each carries
    ``{what_worked, what_didnt, tactical_lessons, category, region,
    outcome}``. When non-empty, a "PAST LESSONS" block is appended to
    the prompt so the negotiator can apply learned tactics.

    Returns ``{draft_text, draft_reasoning}``. On parse / transport error:
    returns a minimal safe fallback. Errors are logged but never raised so
    the routes don't 500.
    """
    fallback = {
        "draft_text": "Hi, is this still available? Would you consider a slightly lower offer?",
        "draft_reasoning": "fallback — LLM call or parse failed; sending a safe opener.",
    }

    # Render the BATNA context into the user message so the LLM sees the
    # other negotiations as a structured block alongside the current
    # conversation + target. The system prompt's "OTHER ACTIVE NEGOTIATIONS"
    # framing keys off this rendered block.
    if not isinstance(batna_context, list):
        batna_context = []
    rendered_batna = _render_batna_context(batna_context)

    if not isinstance(past_lessons, list):
        past_lessons = []
    rendered_lessons = _render_past_lessons(past_lessons)

    user_payload = {
        "current_conversation": conversation,
        "target_price": target_price,
        "other_active_negotiations": batna_context,
        "past_lessons": past_lessons,
    }
    # Inject the rendered context as a side-channel hint so the model
    # sees it pre-formatted; the JSON payload remains the source of
    # truth for structured fields.
    user_payload["__rendered_batna__"] = rendered_batna
    if rendered_lessons:
        user_payload["__rendered_past_lessons__"] = rendered_lessons

    try:
        raw = await _chat_json(_NEGOTIATION_SYSTEM_PROMPT, user_payload)
    except Exception:  # noqa: BLE001
        logger.exception("draft_negotiation: Anthropic call failed; returning fallback.")
        return fallback

    parsed = _parse_json_fallback(raw, fallback)
    if not isinstance(parsed.get("draft_text"), str) or not parsed["draft_text"].strip():
        parsed["draft_text"] = fallback["draft_text"]
    if not isinstance(parsed.get("draft_reasoning"), str):
        parsed["draft_reasoning"] = fallback["draft_reasoning"]
    return parsed


# ---------------------------------------------------------------------------
# Analyzer prompt — post-close structured negotiation analysis.


_ANALYZER_SYSTEM_PROMPT = (
    "You are a post-mortem negotiation analyst. You receive a CLOSED "
    "marketplace negotiation between a buyer agent and a seller. "
    "Produce a structured analysis the buyer can apply to future "
    "negotiations on similar items. Return a JSON object with:\n"
    "  - what_worked (list of short strings, 1-5 entries): specific "
    "tactics or framings that moved the deal forward.\n"
    "  - what_didnt (list of short strings, 0-5 entries): missteps or "
    "rigidity that slowed the deal or cost leverage.\n"
    "  - key_moments (list of {turn_idx, observation}, 0-6 entries): "
    "specific buyer or seller turns that hinged the outcome. "
    "``turn_idx`` is the 0-based index in the transcript.\n"
    "  - tactical_lessons (list of short, generally-applicable strings, "
    "1-5 entries): rules the buyer should re-apply next time on a "
    "similar item. Each lesson under 25 words.\n"
    "  - category (short string): item category — e.g. ``standing desk``, "
    "``mountain bike``, ``mid-century lamp``. Inferred from the listing "
    "+ goal text.\n"
    "  - region (short string): metro / neighborhood region if the "
    "transcript mentions it; otherwise empty string.\n"
    "  - confidence (number 0..1): how strongly you stand by this "
    "analysis. Use low values for very short / no-reply transcripts.\n"
    "Be concrete and tactical, not generic. Output ONLY valid JSON. No "
    "prose, no markdown fences."
)


async def analyze_full_negotiation(
    *,
    negotiation_transcript: list[dict],
    listing: dict,
    outcome: str,
    target_price: float | None,
    final_price: float | None,
    hunt_goal: str,
) -> dict:
    """LLM-driven post-close analyzer. Returns the structured analysis dict.

    ``outcome`` is the closed-state classification — ``"closed_deal"``
    for the winning job, ``"declined"`` for siblings auto-declined by
    the finalize-close flow, ``"no_response"`` when the seller never
    replied, ``"abandoned"`` otherwise.

    On parse / transport error: returns a safe empty-shape fallback so
    the caller can persist *something* to EverOS rather than dropping
    the analysis entirely. Errors are logged but never raised.
    """
    fallback = {
        "what_worked": [],
        "what_didnt": [],
        "key_moments": [],
        "tactical_lessons": [],
        "category": "",
        "region": "",
        "confidence": 0.0,
    }

    user_payload = {
        "hunt_goal": hunt_goal,
        "listing": listing,
        "outcome": outcome,
        "target_price": target_price,
        "final_price": final_price,
        "transcript": negotiation_transcript,
    }
    try:
        raw = await _chat_json(_ANALYZER_SYSTEM_PROMPT, user_payload)
    except Exception:  # noqa: BLE001
        logger.exception(
            "analyze_full_negotiation: Anthropic call failed; returning fallback."
        )
        return fallback

    parsed = _parse_json_fallback(raw, fallback)
    if not isinstance(parsed, dict):
        return fallback
    return parsed
