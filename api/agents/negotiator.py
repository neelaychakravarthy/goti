"""AgentField reasoner: draft the next outbound message in a negotiation.

Shares `app` (and therefore `app.memory` + `app.pause`) with the other
reasoners — see `_af_app.py`. This reasoner is the BATNA-leveraged
step in the parallel-negotiations flow: the FastAPI orchestration
layer pulls the full conversation history for every OTHER active
job in the same hunt and passes it explicitly via ``batna_context``.
The reasoner threads it into the draft prompt as cross-leverage.

The pre-Pass shared-memory BATNA bus (``app.memory.get("batna:...")``)
was the wrong abstraction — it only carried per-job price state, not
the rich conversation transcripts that make leverage feel natural.
The DB has the real conversations; orchestration pulls from there.

After drafting, it calls `app.pause(...)` to wait for human approval via
the approval-card flow. The `POST /api/approvals/{approval_request_id}`
endpoint resumes the paused reasoner.

Verified against agentfield 0.1.84:
- `app.pause(approval_request_id, approval_request_url='', ...)` is async
  and returns an ``agentfield.client.ApprovalResult`` dataclass with fields
  ``decision`` ("approved" | "rejected" | "request_changes" | "expired" |
  "error"), ``feedback`` (str — the user's edited text, if any),
  ``approval_request_id``, ``execution_id``, ``raw_response``.

The unwrap below handles both the real ApprovalResult shape AND a
dict-shaped resume payload (defensive for dev / test paths).
"""

from __future__ import annotations

import logging

from api.agents._af_app import app
from api.llm import draft_negotiation
from api.memory_store import list_top_cases_for_draft

logger = logging.getLogger(__name__)


@app.reasoner()
async def draft_message(
    job_id: str,
    conversation: list[dict],
    target_price: float,
    user_id: str = "",
    batna_context: list[dict] | None = None,
    skip_pause: bool = False,
    listing_category: str = "",
    listing_region: str = "",
) -> dict:
    """Draft the next outbound message for a negotiation; pause for approval.

    ``batna_context`` is the full conversation history for the user's
    OTHER active negotiations in the same hunt, pre-built by FastAPI's
    ``get_batna_context_for_hunt``. Each entry carries
    ``{job_id, listing_title, marketplace, asking_price, target_price,
    status, conversation: [{role, text, sent_at}, ...]}``. The reasoner
    threads these into the LLM prompt so the drafted message can cite
    specific competing offers verbatim.

    If ``skip_pause=True``, the reasoner returns the draft directly
    without calling ``app.pause()`` — FastAPI then orchestrates the
    approval via its own ``approval_queue`` row instead of relying on
    AgentField's pause/resume bridge. The default (False) is the
    paused behaviour used by the hunt lifecycle.

    Calls `app.pause(...)` after drafting. The pause resumes when
    FastAPI handles a `POST /api/approvals/{approval_request_id}` and
    invokes AgentField's resume API with an ``ApprovalResult`` (decision
    in {"approved","rejected","request_changes","expired","error"}, plus
    optional ``feedback`` string carrying the user's edited text).

    Returns:
        ``{
            draft_text: str,              # the LLM's original draft
            draft_reasoning: str,         # why this draft
            approval_status: str,         # "approved" | "rejected" | "request_changes" | "expired" | "error" | "pause_failed" | "skipped"
            sent_text: str | None,        # what the user actually approved (or None on non-approve / skipped)
            approval_request_id: str,     # deterministic key used by FastAPI
        }``
    """
    if not isinstance(batna_context, list):
        batna_context = []

    # Phase H — pull prior analyzed Cases for this category + region so
    # the LLM can apply learned tactics. Best-effort; EverOS failure or
    # empty result degrades to "no past lessons" without raising.
    past_lessons: list[dict] = []
    try:
        past_lessons = await list_top_cases_for_draft(
            user_id=user_id or None,
            category=listing_category or None,
            region=listing_region or None,
            limit=5,
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.exception(
            "negotiator: list_top_cases_for_draft failed job=%s (non-fatal)",
            job_id,
        )
        past_lessons = []

    logger.info(
        "negotiator: drafting job=%s conv_len=%d target_price=%s batna_jobs=%d "
        "past_lessons=%d",
        job_id,
        len(conversation),
        target_price,
        len(batna_context),
        len(past_lessons),
    )
    draft = await draft_negotiation(
        conversation, target_price, batna_context, past_lessons=past_lessons
    )

    approval_request_id = f"job-{job_id}-msg-{len(conversation)}"
    approval_request_url = f"http://localhost:8000/api/jobs/{job_id}"

    # Fast-path: when invoked from FastAPI's negotiate route the caller
    # orchestrates the approval flow via a Postgres approval_queue row,
    # so we skip the pause primitive and return the draft directly.
    if skip_pause:
        return {
            "draft_text": draft.get("draft_text", ""),
            "draft_reasoning": draft.get("draft_reasoning", ""),
            "approval_status": "skipped",
            "sent_text": None,
            "approval_request_id": approval_request_id,
        }

    # Hunt-driven invocations: include a rich payload so the bridge router
    # can synthesize a meaningful approval_needed notification (title,
    # body, deep-link target_href). The bridge tolerates missing keys
    # and falls back to defaults — passing the payload is best-effort.
    draft_text_preview = draft.get("draft_text", "")
    payload = {
        "kind": "approval_needed",
        "title": "Approve outbound message",
        "body": (
            f'Send: "{draft_text_preview[:80]}"'
            if draft_text_preview
            else "Approve the next outbound negotiation message."
        ),
        "job_id": job_id,
        "user_id": user_id,
        "target_href": f"/deal/j-{job_id}",
        "draft_text": draft_text_preview,
        "draft_reasoning": draft.get("draft_reasoning", ""),
        "conversation": conversation,
    }

    try:
        approval = await app.pause(
            approval_request_id=approval_request_id,
            approval_request_url=approval_request_url,
            payload=payload,
        )
    except TypeError:
        # AgentField versions that don't accept ``payload`` on pause();
        # the bridge router still upserts an approval row off the
        # request-approval call, so the user-facing approval card still
        # surfaces — just without the richer payload contextual fields.
        try:
            approval = await app.pause(
                approval_request_id=approval_request_id,
                approval_request_url=approval_request_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "negotiator: app.pause() raised; returning draft without approval."
            )
            return {
                "draft_text": draft.get("draft_text", ""),
                "draft_reasoning": draft.get("draft_reasoning", ""),
                "approval_status": "pause_failed",
                "sent_text": None,
                "approval_request_id": approval_request_id,
                "error": str(exc),
            }
    except Exception as exc:  # noqa: BLE001 — pause() may not behave identically in dev
        logger.exception("negotiator: app.pause() raised; returning draft without approval.")
        return {
            "draft_text": draft.get("draft_text", ""),
            "draft_reasoning": draft.get("draft_reasoning", ""),
            "approval_status": "pause_failed",
            "sent_text": None,
            "approval_request_id": approval_request_id,
            "error": str(exc),
        }

    # Approval comes back as an `ApprovalResult` dataclass (real path) or a
    # dict (dev / test resume paths). Unwrap defensively.
    decision_raw: str
    edited: str | None
    if isinstance(approval, dict):
        decision_raw = str(approval.get("decision", "approved")).lower()
        # Accept either `feedback` (matches ApprovalResult) or `edited_text`
        # (matches FastAPI's request body) as the source of edited text.
        edited = approval.get("feedback") or approval.get("edited_text")
    else:
        # Real ApprovalResult dataclass — has .decision and .feedback.
        decision_raw = str(getattr(approval, "decision", "approved")).lower()
        edited = getattr(approval, "feedback", None) or None

    # Normalize: AgentField uses "approved"/"rejected"; our return contract
    # uses the same vocabulary, but tolerate "approve"/"reject" too.
    if decision_raw in ("approve", "approved"):
        decision = "approved"
    elif decision_raw in ("reject", "rejected"):
        decision = "rejected"
    else:
        decision = decision_raw

    sent_text: str | None
    if decision == "approved":
        sent_text = edited if (isinstance(edited, str) and edited.strip()) else draft.get("draft_text")
    else:
        sent_text = None

    return {
        "draft_text": draft.get("draft_text", ""),
        "draft_reasoning": draft.get("draft_reasoning", ""),
        "approval_status": decision,
        "sent_text": sent_text,
        "approval_request_id": approval_request_id,
    }
