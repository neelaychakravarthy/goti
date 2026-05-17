"""AgentField reasoner: end-of-negotiation classifier (Phase E).

Runs after every new message (buyer or seller) and verdicts whether the
negotiation has reached a natural close-point. The verdict is persisted
to ``Job.ready_to_close`` + ``close_signal_reason`` +
``suggested_close_price`` and surfaced to the UI as a "Ready to close"
badge on the deal page.

Shares ``app`` with the other reasoners (clarifier, valuation,
negotiator, coordinator, picker) — see ``_af_app.py``. Imported by
``api/agents/clarifier.py:main()`` so the ``@app.reasoner()`` decorator
fires when the agent server boots.

The classifier is a pure LLM call (no ``app.pause()``, no shared memory
reads) — it just receives the conversation + listing context and
returns the verdict. Failures fall back to ``ready_to_close=False`` so
a flaky model never false-positives the user into finalize.

Counts as the 5th reasoner toward AgentField's "≥4 reasoners" sponsor
depth requirement (per SPEC.md "Required sponsors / integrations").
"""

from __future__ import annotations

import logging

from api.agents._af_app import app
from api.llm import classify_negotiation_state as _llm_classify

logger = logging.getLogger(__name__)


@app.reasoner()
async def classify_negotiation_state(
    conversation: list,
    listing: dict,
    target_price: float | None = None,
    user_id: str = "",
) -> dict:
    """Classify whether the negotiation is ready to close.

    Args:
        conversation: Full message thread for the job, oldest-first.
            Each entry has ``{role, text, sent_at?}``.
        listing: The listing dict (title, price, marketplace, etc.).
        target_price: The buyer's negotiation target (Job.target_price).
        user_id: Authenticated user id — carried through for logging
            symmetry with the other reasoners; the classifier itself
            doesn't read per-user shared memory.

    Returns:
        ``{ready_to_close: bool, reason: str, suggested_close_price:
        float|null, confidence: float}``. The orchestration layer
        (``api/orchestration/jobs.py::invoke_classifier_for_job``)
        persists this to the Job row.
    """
    logger.info(
        "classify_negotiation_state: job_user=%s messages=%d target=%s",
        user_id,
        len(conversation) if isinstance(conversation, list) else -1,
        target_price,
    )
    if not isinstance(conversation, list):
        conversation = []
    if not isinstance(listing, dict):
        listing = {}
    return await _llm_classify(
        conversation=conversation,
        listing=listing,
        target_price=target_price,
    )
