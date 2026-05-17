"""browser-use Agent runner.

Each ``run_action()`` call:

1. Spawns a Browserbase headless session bound to the user's
   ``context_id`` (cookies persist there from the initial Live View
   login).
2. Constructs a browser-use ``Agent`` whose ``BrowserSession`` is
   connected to Browserbase via the session's ``connect_url`` (CDP).
3. Runs the natural-language task — the agent loops through plan / act /
   observe steps until done or ``max_steps`` is reached.
4. Closes the Browserbase session.

The LLM is Anthropic Claude, reached through ``browser_use.
ChatAnthropic`` — browser-use ships its own Anthropic adapter so we
don't need a separate langchain client.

When ``hunt_id`` is passed, every Agent step is logged to
``hunt_activity_events`` (thinking + next_goal + action_summary)
through the ``register_new_step_callback`` browser-use exposes. The
hunt detail UI polls these rows to render a live reasoning timeline.

**browser-use API as verified against 0.12.6:**

- ``Browser`` is an alias for ``BrowserSession`` — no separate
  ``BrowserConfig`` wrapper. ``BrowserSession(cdp_url=...)`` is the
  documented way to attach to a remote Chrome over the DevTools
  Protocol.
- ``Agent(task=..., llm=..., browser=..., register_new_step_callback=...)``
  — ``browser`` is a ``BrowserSession``. The callback is invoked after
  every successful LLM step with ``(BrowserStateSummary, AgentOutput,
  step_idx)``. ``max_steps`` is passed on ``.run()``, not ``__init__``.
- ``Agent.run()`` returns an ``AgentHistoryList``. We extract the final
  result via ``.final_result()`` (string answer) or
  ``.get_structured_output()`` when ``output_model_schema`` was set.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from api.config import get_settings
from api.integrations.browserbase import client as bb

logger = logging.getLogger(__name__)


class BrowserAgentError(RuntimeError):
    """Raised when prerequisites are missing or the agent run fails fatally."""


@dataclass
class BrowserAgentSession:
    """A long-lived Browserbase session + browser-use ``BrowserSession``
    pair that can be reused across multiple ``run_action`` calls.

    Used by the streaming discovery loop so the agent doesn't have to
    navigate from ``about:blank`` every iteration — the previous
    iteration's final URL (results page or listing detail) is the
    starting state for the next iteration. Saves a navigate step per
    iteration AND Browserbase minutes (one session, many tasks).

    Mint via ``open_browser_agent_session`` + tear down via
    ``close_browser_agent_session``. The session holds the project-wide
    concurrent-sessions semaphore permit for its whole lifetime — release
    it as soon as the marketplace's iteration loop exits.

    The LLM is rebuilt per ``run_action`` call (cheap; the constructor
    just records config). Keeping it off the session lets callers open a
    session without an Anthropic key — useful for tests that monkeypatch
    ``search_one_listing`` and never reach the LLM path.
    """

    session_id: str
    connect_url: str
    browser_session: Any  # browser_use.BrowserSession — typed Any so test fixtures don't need the import


# Concurrent-session enforcement lives one level down in
# ``api.integrations.browserbase.client.create_*`` — those acquire a
# project-wide semaphore so EVERY caller (link flow, validation
# probes, run_action, future paths) is gated. Keeping the gate at
# ``bb.sessions.create`` time means no path can ever exceed the
# concurrent-browsers quota.


async def open_browser_agent_session(
    context_id: str,
) -> BrowserAgentSession:
    """Mint a Browserbase headless session + browser-use ``BrowserSession``
    pair that can be reused across many ``run_action`` calls.

    The streaming discovery loop in ``hunts.py`` opens one of these per
    marketplace, then funnels every ``search_one_listing`` iteration
    through it via ``run_action(session=...)`` so the agent doesn't have
    to re-navigate from ``about:blank`` on every iteration. Saves a
    navigate step AND keeps the same browser state (cookies, scroll
    position, open detail page) live across calls.

    Holds the project-wide concurrent-sessions semaphore for the
    lifetime of the session — callers MUST pair this with
    ``close_browser_agent_session`` (in a ``try/finally``) so a
    cancellation / crash doesn't leak a permit + a Browserbase session.

    Browserbase failures (no slots, network) propagate as their native
    exception types. The Anthropic-key check is deferred to
    ``run_action`` so the session can be opened in test paths that
    never reach the LLM.
    """
    session_id, connect_url = await bb.create_headless_session(context_id)
    try:
        from browser_use import BrowserSession

        browser_session = BrowserSession(cdp_url=connect_url)
        return BrowserAgentSession(
            session_id=session_id,
            connect_url=connect_url,
            browser_session=browser_session,
        )
    except Exception:
        # Mint failed AFTER we acquired the Browserbase session — release
        # it before re-raising so we don't leak the upstream session +
        # the semaphore permit.
        try:
            await asyncio.shield(bb.end_session(session_id))
        except Exception:  # noqa: BLE001 — best-effort
            logger.warning(
                "open_browser_agent_session: end_session failed during error path"
            )
        raise


async def close_browser_agent_session(
    session: BrowserAgentSession | None,
) -> None:
    """Tear down a session opened via ``open_browser_agent_session``.

    Idempotent on ``None`` — callers can pass a possibly-unbuilt session
    without an explicit guard. Each step is shielded from outer
    cancellation so a Pause/Stop click mid-flight still runs cleanup to
    completion.
    """
    if session is None:
        return
    try:
        await asyncio.shield(session.browser_session.kill())
    except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
        if isinstance(exc, asyncio.CancelledError):
            raise
        logger.warning(
            "close_browser_agent_session: browser_session.kill() raised: %s",
            exc,
        )
    try:
        await asyncio.shield(bb.end_session(session.session_id))
    except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
        if isinstance(exc, asyncio.CancelledError):
            raise
        logger.warning(
            "close_browser_agent_session: bb.end_session raised: %s", exc
        )


async def run_action(
    context_id: str | None,
    task: str,
    *,
    max_steps: int = 25,
    hunt_id: str | None = None,
    job_id: str | None = None,
    phase: str | None = None,
    session: Optional[BrowserAgentSession] = None,
) -> dict[str, Any] | list[Any] | str:
    """Run a browser-use Agent task against a Browserbase session bound to ``context_id``.

    Two lifetimes for the underlying Browserbase session:

    - ``session=None`` (default) — mint + tear down a fresh session
      around this single task. Used by one-off paths
      (``send_message``, ``fetch_replies``) where the browser state
      doesn't need to carry across calls. ``context_id`` is required.
    - ``session=BrowserAgentSession`` — reuse a session minted by
      ``open_browser_agent_session``. Used by the streaming discovery
      loop so the agent's next iteration starts on the previous
      iteration's final URL (saves a navigate). The caller owns the
      session lifecycle; this function does NOT close it. When passed,
      ``context_id`` is ignored.

    Returns the agent's final output, best-effort coerced to a Python
    object: ``dict`` / ``list`` when the agent returned JSON, otherwise
    the raw string. Callers wrap this in their own defensive parsing —
    see ``actions._parse_listings`` for the pattern.

    When ``hunt_id`` is provided, each Agent step is logged to
    ``hunt_activity_events`` so the hunt detail UI can render a live
    reasoning timeline. ``phase`` is a short label
    (``discovery`` / ``send_message`` / ``fetch_replies``).

    Raises ``BrowserAgentError`` on missing config; lower-level errors
    (Browserbase unreachable, LLM 5xx) propagate as their native
    exception types.
    """
    own_session = session is None
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise BrowserAgentError(
            "ANTHROPIC_API_KEY required for browser-agent (LLM)"
        )

    # Surface queue contention to the hunt activity timeline so the
    # user sees "Queued — waiting for Browserbase session" instead of
    # a mysterious silent stall. Only relevant when we're about to
    # mint a fresh session — a reused session has already crossed the
    # gate at open_browser_agent_session time.
    if hunt_id and own_session:
        try:
            from api.integrations.browserbase.client import _get_session_semaphore

            if _get_session_semaphore().locked():
                await _log_queue_event(
                    hunt_id=hunt_id, job_id=job_id, phase=phase or ""
                )
        except Exception:  # noqa: BLE001
            logger.debug("queue-event introspection failed", exc_info=True)

    # 1. Resolve the session (mint a new one OR reuse the caller's).
    if own_session:
        if not context_id:
            raise BrowserAgentError(
                "run_action requires context_id when no pre-built session is given"
            )
        session = await open_browser_agent_session(context_id)
    assert session is not None  # for the type checker
    try:
        # 2. Build the LLM + Agent for this task. The LLM constructor is
        # cheap (just records model id + key), so we build per-call
        # rather than caching on the session — keeps the
        # anthropic_api_key requirement local to actual LLM work.
        llm = _build_llm(settings)
        from browser_use import Agent

        step_callback = (
            _make_step_logger(hunt_id=hunt_id, job_id=job_id, phase=phase or "")
            if hunt_id
            else None
        )
        # ``max_failures`` defaults to 5 in browser-use. Keep it at 3
        # for our use case — enough to ride out a flaky tool call or
        # two (Sonnet occasionally emits malformed ``action`` blocks)
        # without letting the agent grind through many failed steps.
        agent = Agent(
            task=task,
            llm=llm,
            browser=session.browser_session,
            register_new_step_callback=step_callback,
            max_failures=3,
        )
        # Hard ceiling on a single run_action call, purely as a
        # safety net against truly-wedged tasks (LLM call that never
        # returns, dropped CDP message, etc.). 10 minutes is FAR
        # above the worst-case step count × per-step latency for our
        # tasks — the hunt-level controls (per-marketplace cap +
        # user-driven pause/stop) are the real limits on how long
        # discovery runs.
        history = await asyncio.wait_for(
            agent.run(max_steps=max_steps),
            timeout=600.0,
        )

        # 3. Coerce the result into a dict / list / string.
        return _parse_agent_output(history)

    finally:
        # Always close the Agent (it has its own internal event bus)
        # — even when the BrowserSession is owned by the caller, the
        # per-task Agent isn't reusable so we tear it down here.
        try:
            if "agent" in locals():
                await asyncio.shield(agent.close())
        except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.warning("run_action: agent.close() raised: %s", exc)
        # Tear down the BrowserSession + Browserbase session ONLY when
        # we minted them. When the caller passed a session, they own
        # the lifecycle and we leave it open for the next iteration.
        if own_session:
            await close_browser_agent_session(session)


_PHASE_LABEL: dict[str, str] = {
    "discovery": "discovery",
    "send_message": "sending a message",
    "fetch_replies": "checking for a reply",
}


async def _log_queue_event(*, hunt_id: str, job_id: str | None, phase: str) -> None:
    """Append a ``Queued — waiting for Browserbase session`` row to
    ``hunt_activity_events`` so the live timeline shows when a task
    is parked behind the concurrent-sessions semaphore.

    Written with ``step_idx=0`` so the UI can render it distinctly from
    in-flight LLM steps (which start at index 1). Best-effort: a logging
    failure must never crash the surrounding ``run_action``.
    """
    try:
        from api.db import AsyncSessionLocal
        from api.models import HuntActivityEvent

        label = _PHASE_LABEL.get(phase, phase or "browser-agent task")
        async with AsyncSessionLocal() as s:
            await HuntActivityEvent.insert(
                s,
                hunt_id=hunt_id,
                job_id=job_id,
                phase=phase or "",
                step_idx=0,
                action_summary=f"queued: {label}",
                next_goal=(
                    "Queued behind another in-flight browser task — will "
                    "start as soon as a Browserbase slot frees up."
                ),
            )
    except Exception:  # noqa: BLE001 — telemetry, never crash the agent
        logger.exception(
            "_log_queue_event: failed to persist queue notice hunt=%s phase=%s",
            hunt_id,
            phase,
        )


def _make_step_logger(*, hunt_id: str, job_id: str | None, phase: str):
    """Build the per-step callback browser-use calls after each LLM turn.

    The callback receives ``(BrowserStateSummary, AgentOutput,
    step_idx)``. It writes one ``hunt_activity_events`` row capturing
    the model's thinking + next_goal + a short action summary. All
    failures are logged and swallowed — losing a single activity event
    must never crash the Agent loop.
    """

    async def _on_step(state_summary, agent_output, step_idx) -> None:  # type: ignore[ANN001]
        try:
            thinking = getattr(agent_output, "thinking", None)
            next_goal = getattr(agent_output, "next_goal", None)
            action_summary = _summarize_actions(getattr(agent_output, "action", None))
            url = getattr(state_summary, "url", None)

            from api.db import AsyncSessionLocal
            from api.models import HuntActivityEvent

            async with AsyncSessionLocal() as s:
                await HuntActivityEvent.insert(
                    s,
                    hunt_id=hunt_id,
                    job_id=job_id,
                    phase=phase,
                    step_idx=int(step_idx) if step_idx is not None else 0,
                    thinking=thinking,
                    next_goal=next_goal,
                    action_summary=action_summary,
                    url=url,
                )
        except Exception:  # noqa: BLE001 — never crash the agent on logging
            logger.exception(
                "_on_step: failed to persist activity event hunt=%s phase=%s step=%s",
                hunt_id,
                phase,
                step_idx,
            )

    return _on_step


def _summarize_actions(actions: Any) -> str | None:
    """Turn a ``list[ActionModel]`` into a short human-readable summary.

    Each ActionModel is a one-key dict like ``{"click_element_by_index":
    {"index": 12}}``. We grab the first key (the action verb) and join
    multiple actions with " → " so the UI can render a compact label.
    """
    if not actions:
        return None
    parts: list[str] = []
    for a in actions:
        # ActionModel is a Pydantic model — dump to dict, take the first key.
        if hasattr(a, "model_dump"):
            d = a.model_dump(exclude_none=True)
        elif isinstance(a, dict):
            d = a
        else:
            continue
        for key, val in d.items():
            if key == "done" and isinstance(val, dict) and "text" in val:
                parts.append(f"done: {str(val['text'])[:80]}")
            else:
                parts.append(key)
            break
        if len(parts) >= 4:
            break
    return " → ".join(parts) if parts else None


def _build_llm(settings):
    """Construct the ChatAnthropic client browser-use's Agent will use.

    browser-use ships its own ``ChatAnthropic`` adapter
    (``browser_use.llm.anthropic.chat.ChatAnthropic``) that wraps the
    official Anthropic SDK. No langchain needed.

    Uses ``claude_browser_model_id`` (Sonnet by default) — the
    ``AgentOutput`` schema browser-use forces via tool-call has many
    required fields (thinking + memory + next_goal + list[action]) and
    Haiku occasionally drops ``action`` under that pressure. Sonnet is
    reliable on this schema.
    """
    from browser_use import ChatAnthropic

    return ChatAnthropic(
        model=settings.claude_browser_model_id,
        api_key=settings.anthropic_api_key,
        temperature=0.2,
    )


def _parse_agent_output(raw: Any) -> dict[str, Any] | list[Any] | str:
    """Best-effort coerce the agent's history / final result into a Python object.

    browser-use's ``Agent.run()`` returns an ``AgentHistoryList``; its
    ``.final_result()`` is the LLM's last textual answer. We try to
    parse that as JSON (the actions craft their tasks to demand a JSON
    response) and fall back to the raw string when it isn't valid JSON.
    """
    # AgentHistoryList exposes ``final_result()`` — strip to a string.
    text: Any = raw
    if hasattr(raw, "final_result"):
        try:
            text = raw.final_result()
        except Exception:  # noqa: BLE001 — defensive
            logger.exception(
                "_parse_agent_output: final_result() raised; falling back to repr"
            )
            text = repr(raw)

    # Already structured? Return as-is.
    if isinstance(text, (dict, list)):
        return text

    if text is None:
        return ""

    text = str(text).strip()

    # Strip markdown code fences if the agent wrapped JSON in ```json ... ```.
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Repair pass: LLMs frequently emit JSON with embedded literal
    # newlines / carriage returns / tabs inside string values, which is
    # invalid JSON and would otherwise force us to throw the listing
    # away. We don't know which characters are inside strings vs. JSON
    # whitespace, so we use a permissive parser via
    # ``json.loads(strict=False)`` first (allows raw control chars in
    # strings), then fall back to escaping every control char in the
    # whole blob and re-parsing.
    try:
        return json.loads(text, strict=False)
    except (json.JSONDecodeError, ValueError):
        pass

    # Escape every literal control character. This corrupts JSON
    # whitespace too, but ``json.loads`` is tolerant of the resulting
    # extra ``\n`` between tokens.
    escaped = (
        text.replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
        .replace("\t", "\\t")
    )
    try:
        return json.loads(escaped)
    except (json.JSONDecodeError, ValueError):
        # Last-ditch: locate the first ``{`` and last ``}`` and parse
        # the slice — handles cases where the model added stray prose
        # before / after the JSON.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            slice_text = text[start : end + 1]
            for candidate in (
                slice_text,
                slice_text.replace("\n", "\\n")
                .replace("\r", "\\n")
                .replace("\t", "\\t"),
            ):
                try:
                    return json.loads(candidate, strict=False)
                except (json.JSONDecodeError, ValueError):
                    continue
        logger.warning(
            "_parse_agent_output: failed every JSON-parse strategy; "
            "returning raw string (first 200 chars=%r)",
            text[:200],
        )
        return text
