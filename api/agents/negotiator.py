"""AgentField reasoner: draft the next outbound message in a negotiation.

Shares `app` (and therefore `app.memory` + `app.pause`) with the other three
reasoners — see `_af_app.py`. This reasoner is the BATNA-leveraged step in
the parallel-negotiations flow: it reads the user's other active job states
from `app.memory[f"batna:{user_id}"]` and threads them into the draft.

After drafting, it calls `app.pause(...)` to wait for human approval via
the approval-card flow. Pass 2 wires the corresponding `POST
/api/jobs/{job_id}/approvals/{card_id}` endpoint that resumes the paused
reasoner.

Verified against agentfield 0.1.84 during Pass 1:
- `app.memory.get(key, default=None)` and `app.memory.set(key, data)` are
  both async coroutines.
- `app.pause(approval_request_id, approval_request_url='', ...)` is async
  and returns an ``agentfield.client.ApprovalResult`` dataclass with fields
  ``decision`` ("approved" | "rejected" | "request_changes" | "expired" |
  "error"), ``feedback`` (str — the user's edited text, if any),
  ``approval_request_id``, ``execution_id``, ``raw_response``.

The unwrap below handles both the real ApprovalResult shape AND a
dict-shaped resume payload (defensive for dev / mock-resume paths).
"""

from __future__ import annotations

import logging

from api.agents._af_app import app
from api.llm import draft_negotiation

logger = logging.getLogger(__name__)


@app.reasoner()
async def draft_message(
    job_id: str,
    conversation: list[dict],
    target_price: float,
    user_id: str = "demo_user",
    skip_pause: bool = False,
) -> dict:
    """Draft the next outbound message for a negotiation; pause for approval.

    Pulls BATNA state for `user_id`'s OTHER active negotiations from shared
    memory (key: ``batna:{user_id}``) and includes it in the prompt so the
    drafted message can cite competing offers as leverage.

    If ``skip_pause=True`` (Pass 2 FastAPI integration), the reasoner returns
    the draft directly without calling ``app.pause()`` — FastAPI then
    orchestrates the approval via its own ``approval_queue`` row instead of
    relying on AgentField's pause/resume bridge. The default (False)
    preserves the original Pass 1 behavior of pausing.

    Calls `app.pause(...)` after drafting. The pause resumes when FastAPI
    (Pass 2) handles a `POST /api/jobs/{job_id}/approvals/{card_id}` and
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
    try:
        batna_state = await app.memory.get(f"batna:{user_id}")
    except Exception:  # noqa: BLE001
        logger.exception("negotiator: app.memory.get failed; proceeding without BATNA state.")
        batna_state = None
    if not isinstance(batna_state, dict):
        batna_state = {}

    logger.info(
        "negotiator: drafting job=%s conv_len=%d target_price=%s batna_jobs=%d",
        job_id,
        len(conversation),
        target_price,
        len(batna_state),
    )
    draft = await draft_negotiation(conversation, target_price, batna_state)

    approval_request_id = f"job-{job_id}-msg-{len(conversation)}"
    approval_request_url = f"http://localhost:8000/api/jobs/{job_id}"

    # Pass-2 fast-path: when invoked from FastAPI's negotiate route the
    # caller orchestrates the approval flow via a Postgres approval_queue
    # row, so we skip the pause primitive and return the draft directly.
    if skip_pause:
        return {
            "draft_text": draft.get("draft_text", ""),
            "draft_reasoning": draft.get("draft_reasoning", ""),
            "approval_status": "skipped",
            "sent_text": None,
            "approval_request_id": approval_request_id,
        }

    try:
        approval = await app.pause(
            approval_request_id=approval_request_id,
            approval_request_url=approval_request_url,
        )
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
    # dict (dev / mock-resume paths). Unwrap defensively.
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
