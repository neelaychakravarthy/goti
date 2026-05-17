"""High-level marketplace actions executed by the browser-use agent.

Each action crafts a natural-language task designed to produce
structured JSON, calls ``client.run_action()`` against the user's
Browserbase context, then parses the result into our Pydantic contract
types. Failures degrade gracefully (return ``[]`` / a synthetic
``MessageId``) so the hunt + job lifecycles never block on a single
flaky run.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from api.contracts import Listing, MessageId, Reply
from api.integrations.browser_agent import client as agent

logger = logging.getLogger(__name__)


@dataclass
class ClarificationRequest:
    """Sentinel returned by ``search_one_listing`` when the agent
    couldn't tell whether the listings on the page match the user's
    goal and needs the user to clarify before continuing.

    Holds the agent's natural-language question + a one-sentence
    context the streaming discovery loop surfaces in the notification.
    """

    question: str
    context: str = ""


# Public landing pages for each marketplace — the agent task seeds the
# search from these URLs. Login state lives in the Browserbase Context
# so the agent doesn't need to handle credential entry.
_MARKETPLACE_URLS: dict[str, str] = {
    "fb": "https://www.facebook.com/marketplace",
    "nextdoor": "https://nextdoor.com",
    "offerup": "https://offerup.com",
    "craigslist": "https://craigslist.org",
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


async def search_one_listing(
    context_id: str,
    query: str,
    marketplace: str,
    exclude: list[dict],
    *,
    hunt_id: str | None = None,
    session: "agent.BrowserAgentSession | None" = None,
) -> Listing | ClarificationRequest | None:
    """Find ONE listing on ``marketplace`` matching ``query``.

    Single short browser-use task (≤8 steps) so each call fits well
    inside a Browserbase free-tier session window — no risk of the
    HTTP 410 cascade we hit when running a 30-step "find everything at
    once" task.

    When ``session`` is provided, the underlying ``run_action`` reuses
    that long-lived Browserbase session across iterations — the agent's
    next iteration picks up wherever the previous one left off
    (results page, detail page, etc.) rather than restarting from
    ``about:blank``. The streaming discovery loop in ``hunts.py``
    opens one session per marketplace and threads it through every
    ``search_one_listing`` call.

    ``exclude`` is a list of ``{id, title, url}`` dicts for listings
    already surfaced in prior iterations. Both title + url are passed
    so the agent can recognise dupes during the results-page scan
    (matching by title text) instead of having to click into each
    listing to read its opaque post id. Returns ``None`` when no
    fresh match is found, when the agent errored, or when the result
    fails to validate against ``Listing``.
    """
    if marketplace not in _MARKETPLACE_URLS:
        return None
    base_url = _MARKETPLACE_URLS[marketplace]
    # Build a compact, agent-readable exclude list: one bullet per
    # already-surfaced listing with the title (human-readable, visible
    # on the results page) + url (sometimes visible as the link target
    # on hover). Capped at 30 entries to keep the prompt short — older
    # surfaced listings are typically off the first page of results
    # anyway.
    exclude_blurb = ""
    if exclude:
        compact = []
        for ex in exclude[:30]:
            if not isinstance(ex, dict):
                continue
            title = str(ex.get("title") or "").strip().replace("\n", " ")
            ex_url = str(ex.get("url") or "").strip()
            ex_id = str(ex.get("id") or "").strip()
            if not title and not ex_url and not ex_id:
                continue
            parts = []
            if title:
                parts.append(f'"{title[:80]}"')
            if ex_url:
                parts.append(ex_url)
            elif ex_id:
                parts.append(f"id={ex_id}")
            compact.append(f"  - {' — '.join(parts)}")
        if compact:
            exclude_blurb = (
                "\n\nALREADY-SURFACED LISTINGS — do NOT re-pick these. "
                "Recognise them by their title (visible on the search "
                "results page) and skip past them during the scan in "
                "step 2; don't click into them only to discover they "
                "match:\n" + "\n".join(compact)
            )
    task = (
        f"You are searching {marketplace} for second-hand listings that "
        f'match this user goal: "{query}".\n'
        f"\n"
        f"YOUR JOB — BE FAST AND DECISIVE. You have a tight step "
        f"budget, so DO NOT analyze every listing in detail. Workflow:\n"
        f"\n"
        f"1. GET TO SEARCH RESULTS. Check the current browser URL "
        f"FIRST:\n"
        f"   - If you're already on a search results page for "
        f'"{query}" on {marketplace}, STAY THERE — do not re-navigate. '
        f"Scroll if you need to find listings you haven't already "
        f"surfaced (see ALREADY-SURFACED list below).\n"
        f"   - If you're on a listing detail page (a previous iteration "
        f"clicked into one and emitted `done`), click Back / use "
        f"`go_back` to return to the results page. Do NOT navigate "
        f"from scratch.\n"
        f"   - Only if the browser is on `about:blank` or an unrelated "
        f"page, open {base_url} and run the search.\n"
        f"2. SCAN the result titles + prices (only — don't read "
        f"descriptions yet). Filter out:\n"
        f"   (a) obvious mismatches: accessories masquerading as the "
        f"item (e.g. a 'standing desk STOOL' isn't a standing desk; a "
        f"'desk converter' isn't a full desk; a 'monitor mount' isn't a "
        f"desk).\n"
        f"   (b) **any title that matches the ALREADY-SURFACED LISTINGS "
        f"block below**. Skip those at the title-scan stage. Do NOT "
        f"click into them.\n"
        f"Keep listings whose title clearly names the user's item AND "
        f"is not already-surfaced.\n"
        f"3. From the kept listings, pick the SINGLE best match — "
        f"strongest relevance to the goal + price within range + "
        f"reasonable location. ONE pick, NOT a comparison essay.\n"
        f"4. Click into that listing's detail page.\n"
        f"5. Extract the fields below and emit `done`.\n"
        f"\n"
        f"COMMIT TO YOUR PICK. Do NOT use `go_back` to re-evaluate "
        f"other listings. If the detail page reveals your pick "
        f"doesn't actually match (e.g. title says 'standing desk' but "
        f"description says 'overbed table'), emit `done` with empty "
        f"`{{}}` and stop. We'd rather skip a marketplace than burn "
        f"the entire step budget chasing a perfect match.\n"
        f"{exclude_blurb}\n"
        f"\n"
        f"FIELDS to emit (JSON object via `done`):\n"
        f"  id — unique listing id from the URL\n"
        f"  title — listing title (no newlines)\n"
        f"  price — number, USD, integer or float, no $ sign\n"
        f'  marketplace — "{marketplace}"\n'
        f"  url — absolute detail-page URL\n"
        f"  image_url — STRICT RULE: set this to `null` unless the "
        f"page literally shows a string like "
        f"`https://images.craigslist.org/...jpg` (or equivalent for the "
        f"marketplace) that you can copy verbatim. **DO NOT call "
        f"`find_elements` to hunt for img.src attributes. DO NOT "
        f"construct/guess image URLs from thumbnail ids.** If the image "
        f"is rendered as an `<img>` whose src isn't visible to you, "
        f"that's fine — emit null. We'd rather have null than a "
        f"guessed-wrong URL.\n"
        f"  seller_name — if shown; else null\n"
        f"  location — if shown; else null\n"
        f"  description — first ~200 chars of the description text\n"
        f"\n"
        f"CRITICAL — JSON HYGIENE: every string value (title, "
        f"description, location, etc.) must be a SINGLE LINE. Replace "
        f"every newline, carriage return, and tab with a space before "
        f"emitting. Newlines inside JSON string values break parsing on "
        f"our end and we will throw the result away. Also use plain "
        f"ASCII characters where possible — replace fancy dashes "
        f"(en-dash, em-dash) with regular hyphens, smart quotes with "
        f"straight quotes.\n"
        f"\n"
        f"IF NO LISTING ON THIS MARKETPLACE GENUINELY MATCHES the user's "
        f"goal, emit `done` with an empty object `{{}}`. We'd rather get "
        f"an honest 'nothing matches' than a tangentially-related "
        f"listing.\n"
        f"\n"
        f"IF YOU CANNOT TELL whether listings match the user's intent "
        f"(e.g. the goal is 'standing desk' but you're only seeing "
        f"'standing desk stools' and 'standing desk converters' — "
        f"adjacent items where you'd need to know whether the user "
        f"considers those acceptable), DO NOT GUESS. Instead, emit "
        f"`done` with a clarification request shaped like:\n"
        f'  {{"needs_clarification": true, "question": "<a short, '
        f'specific yes/no or pick-one question for the user>", '
        f'"context": "<one short sentence explaining what you saw '
        f'that made you ask>"}}\n'
        f"Pause discovery; the user will answer and you'll get a "
        f"refined goal on the next iteration. Use this sparingly — only "
        f"when there's a real ambiguity that changes which listings "
        f"qualify.\n"
        f"\n"
        f"IMPORTANT: use semantic browser actions only (click, scroll, "
        f"extract_content, go_to_url, type). **DO NOT use `evaluate` "
        f"to run JavaScript and DO NOT use `find_elements` to hunt for "
        f"specific element attributes** — those are not on the allowed "
        f"action list. Once you have title + price + url + location + "
        f"description, you have enough. Emit `done` immediately with "
        f"null for anything else. Spending extra steps to find an "
        f"image URL is a regression; null is the correct value when "
        f"you don't see a literal URL string."
    )
    try:
        # No tight per-call step cap. The hunt-level controls are the
        # only real limits: per-marketplace listing cap (5) +
        # pause/stop/delete from the user. Within a single
        # ``run_action`` we give the agent plenty of headroom (100
        # steps) so a confused iteration doesn't silently fall off the
        # cliff — if the agent keeps going past that, something is
        # actually broken and ``max_failures`` will catch it.
        raw = await agent.run_action(
            context_id,
            task,
            max_steps=100,
            hunt_id=hunt_id,
            phase="discovery",
            session=session,
        )
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        # Browserbase quota errors must propagate — the discovery loop
        # needs to know to stop iterating + emit a user-facing
        # "upgrade Browserbase" notification instead of silently
        # marking the hunt empty.
        from api.integrations.browserbase.client import BrowserbaseQuotaExhausted

        if isinstance(exc, BrowserbaseQuotaExhausted):
            raise
        logger.exception(
            "search_one_listing: agent run failed marketplace=%s",
            marketplace,
        )
        return None

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(raw, dict) or not raw:
        return None
    # Clarification request — the agent saw ambiguous results and is
    # asking the user a question rather than guessing.
    if raw.get("needs_clarification") is True:
        question = str(raw.get("question") or "").strip()
        context = str(raw.get("context") or "").strip()
        if not question:
            logger.warning(
                "search_one_listing: agent emitted needs_clarification "
                "with no question marketplace=%s raw=%r",
                marketplace,
                raw,
            )
            return None
        return ClarificationRequest(question=question, context=context)
    # Real listing match.
    if "id" not in raw:
        return None
    try:
        return Listing.model_validate(raw)
    except Exception:  # noqa: BLE001 — per-listing degrade
        logger.warning(
            "search_one_listing: failed to validate result marketplace=%s "
            "raw=%r",
            marketplace,
            raw,
        )
        return None


async def search_listings(
    context_id: str,
    query: str,
    marketplaces: list[str],
    max_per_source: int = 5,
    *,
    hunt_id: str | None = None,
) -> list[Listing]:
    """Search the user's logged-in marketplaces for ``query``.

    Returns up to ``max_per_source`` ``Listing`` objects per marketplace.
    Marketplaces the user isn't logged into are silently skipped by the
    agent (the task instructs that).

    Kept for back-compat / tests; the production hunt lifecycle uses
    ``search_one_listing`` in a streaming loop instead so candidates
    surface one-at-a-time.

    When ``hunt_id`` is passed, each Agent step is recorded to the
    hunt's activity timeline (``phase="discovery"``).
    """
    targets = [m for m in marketplaces if m in _MARKETPLACE_URLS]
    if not targets:
        return []

    base_urls = {m: _MARKETPLACE_URLS[m] for m in targets}
    task = (
        f"You are searching for second-hand listings matching: \"{query}\".\n"
        f"Search on these marketplaces in order: {', '.join(targets)}.\n"
        f"For each marketplace, find up to {max_per_source} relevant listings.\n"
        f"For each listing, extract: id (from URL; the unique listing identifier), "
        f"title, price (number, USD; integer or float; no $ sign), "
        f"marketplace (one of {targets}), url (absolute), image_url (or null), "
        f"seller_name (or null), location (or null), description "
        f"(first 200 chars, or null).\n"
        f"Return ONLY a JSON array (no prose, no markdown) in this shape:\n"
        f'[{{"id": "...", "title": "...", "price": 0, "marketplace": "fb", '
        f'"url": "...", "image_url": null, "seller_name": null, '
        f'"location": null, "description": null}}]\n'
        f"If a marketplace requires login that hasn't been completed, "
        f"skip it silently. Marketplace base URLs: {base_urls}\n"
        # Anti-`evaluate` constraint. Sonnet 4.x will occasionally pick
        # the ``evaluate`` (run-JavaScript) action and emit the embedded
        # JS source as a quoted string inside the JSON tool call. That
        # crashes browser-use's pydantic parser because the action arg
        # arrives as a string instead of a list — the JS payload contains
        # unescaped quotes that the recovery path can't salvage. Forcing
        # semantic browser actions sidesteps the whole class.
        "IMPORTANT: use semantic browser actions only (click, scroll, "
        "extract_content, go_to_url, type). DO NOT use the `evaluate` "
        "action to run JavaScript — read listing details from the rendered "
        "page text via extract_content."
    )

    try:
        raw = await agent.run_action(
            context_id,
            task,
            max_steps=30,
            hunt_id=hunt_id,
            phase="discovery",
        )
    except Exception:  # noqa: BLE001 — discovery failures degrade gracefully
        logger.exception(
            "search_listings: agent run failed for context=%s query=%r",
            context_id,
            query,
        )
        return []
    return _parse_listings(raw)


def _parse_listings(raw: Any) -> list[Listing]:
    """Defensive parser. Accepts a list, a dict-wrapped list, or a raw string.

    Logs + skips individual malformed entries so a single bad listing
    doesn't poison the whole batch.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.info("_parse_listings: agent returned non-JSON string; ignoring")
            return []
    if isinstance(raw, dict):
        # The agent occasionally wraps the array in a key like
        # ``listings`` or ``results`` — accept both.
        for key in ("listings", "results", "items", "data"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        return []

    out: list[Listing] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        try:
            out.append(Listing.model_validate(item))
        except Exception:  # noqa: BLE001 — per-listing degrade
            logger.warning("_parse_listings: failed validate idx=%d: %r", idx, item)
            continue
    return out


# ---------------------------------------------------------------------------
# Negotiation — send + fetch
# ---------------------------------------------------------------------------


async def send_message(
    context_id: str,
    listing_url: str,
    listing_id: str,
    message_text: str,
    marketplace: str,
    *,
    hunt_id: str | None = None,
    job_id: str | None = None,
) -> MessageId:
    """Open a listing + send the seller a message via the user's session.

    Returns a synthetic ``MessageId`` — marketplaces don't reliably
    expose a stable id on the conversation page, so we mint one for our
    own audit trail.

    When ``hunt_id`` is passed, each Agent step is recorded to the
    hunt's activity timeline (``phase="send_message"``).
    """
    task = (
        f"Open this marketplace listing: {listing_url}\n"
        f"Find and click the 'Message seller' or 'Contact' button.\n"
        f"In the message text area, type EXACTLY this text (no edits, no typos):\n"
        f'"{message_text}"\n'
        f"Click the Send button. Wait for confirmation that the message was sent.\n"
        f"Return ONLY a JSON object (no prose, no markdown):\n"
        f'{{"sent": true, "error": null}} on success, '
        f'{{"sent": false, "error": "<reason>"}} on failure.\n'
        "IMPORTANT: use semantic browser actions only (click, type, "
        "scroll). DO NOT use the `evaluate` action to run JavaScript."
    )

    try:
        raw = await agent.run_action(
            context_id,
            task,
            max_steps=20,
            hunt_id=hunt_id,
            job_id=job_id,
            phase="send_message",
        )
    except Exception:  # noqa: BLE001 — surface as a flagged MessageId
        logger.exception(
            "send_message: agent run failed listing=%s marketplace=%s",
            listing_id,
            marketplace,
        )
        return MessageId(f"bb-{marketplace}-{listing_id}-err")

    sent = isinstance(raw, dict) and bool(raw.get("sent"))
    if not sent:
        err = raw.get("error") if isinstance(raw, dict) else "unknown agent failure"
        logger.warning(
            "send_message: agent did not confirm send listing=%s err=%s raw=%r",
            listing_id,
            err,
            raw,
        )
    return MessageId(f"bb-{marketplace}-{listing_id}-{uuid.uuid4().hex[:8]}")


async def fetch_replies(
    context_id: str,
    listing_url: str,
    listing_id: str,
    marketplace: str,
    since_ts: float,
    *,
    hunt_id: str | None = None,
    job_id: str | None = None,
) -> list[Reply]:
    """Open the conversation thread + extract seller replies after ``since_ts``.

    Empty list on no replies, error, or conversation-not-found — the
    polling caller distinguishes these via repeated calls + a timeout.

    When ``hunt_id`` is passed, each Agent step is recorded to the
    hunt's activity timeline (``phase="fetch_replies"``).
    """
    task = (
        f"Open this marketplace listing's conversation: {listing_url}\n"
        f"Navigate to the messages / inbox / conversation view for this listing.\n"
        f"Find any messages from the SELLER (not yourself) received after "
        f"Unix timestamp {since_ts}.\n"
        f"Return ONLY a JSON array (no prose, no markdown):\n"
        f'[{{"text": "<message text>", "sent_at": <number unix timestamp>}}]\n'
        f"If no new messages, return []. If the conversation cannot be found, "
        f"return [].\n"
        "IMPORTANT: use semantic browser actions only (click, scroll, "
        "extract_content). DO NOT use the `evaluate` action to run JavaScript."
    )

    try:
        raw = await agent.run_action(
            context_id,
            task,
            max_steps=25,
            hunt_id=hunt_id,
            job_id=job_id,
            phase="fetch_replies",
        )
    except Exception:  # noqa: BLE001 — degrade to empty
        logger.exception(
            "fetch_replies: agent run failed listing=%s marketplace=%s",
            listing_id,
            marketplace,
        )
        return []

    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        candidates = (
            raw.get("messages")
            or raw.get("replies")
            or raw.get("items")
            or raw.get("data")
        )
        items = candidates if isinstance(candidates, list) else []
    else:
        items = []

    out: list[Reply] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("body") or ""
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            sent_at = float(item.get("sent_at", since_ts))
        except (TypeError, ValueError):
            sent_at = since_ts
        out.append(
            Reply(
                message_id=MessageId(
                    f"bb-{marketplace}-reply-{listing_id}-{uuid.uuid4().hex[:8]}"
                ),
                listing_id=listing_id,
                sender="seller",
                text=text.strip(),
                received_at=sent_at,
            )
        )
    return out
