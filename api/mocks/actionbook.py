"""Deterministic Actionbook mock — ``send_message`` + ``fetch_replies``.

Used by Stream B's negotiator agent (and any other caller) when
``GOTI_USE_MOCKS=1``. Stream C will reconcile this at convergence — the
real ``api/integrations/actionbook/*.py`` wrappers and this mock share the
same surface area per the SPEC.md B<->C contract.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Reply:
    """One seller reply fetched from the mocked Actionbook session."""

    id: str
    listing_id: str
    text: str
    received_at: float


def send_message(user_id: str, listing_id: str, text: str) -> str:
    """Fake-send a message; return a synthetic ``message_id``.

    Real Actionbook MCP `send_message` returns the platform's message_id;
    this mock returns ``mock-msg-<uuid8>`` to match that shape. Logs the
    call at INFO so devs can verify the negotiator -> Actionbook seam is
    being exercised end-to-end.
    """
    message_id = f"mock-msg-{uuid.uuid4().hex[:8]}"
    logger.info(
        "[MOCK actionbook.send_message] user=%s listing=%s msg_id=%s text=%r",
        user_id,
        listing_id,
        message_id,
        text[:80],
    )
    return message_id


def fetch_replies(user_id: str, listing_id: str, since_ts: float) -> list[Reply]:
    """Return 0 or 1 fixture reply, alternating by ``since_ts`` parity.

    Determinism: an even ``int(since_ts)`` returns one mock reply; odd
    returns none. This simulates a seller responding ~every other poll so
    the polling loop in Pass 2 / future increments can be exercised
    without flake.
    """
    now = time.time()
    if int(since_ts) % 2 == 0:
        return [
            Reply(
                id=f"mock-reply-{uuid.uuid4().hex[:8]}",
                listing_id=listing_id,
                text="Still available! What's your best offer?",
                received_at=now,
            )
        ]
    logger.debug(
        "[MOCK actionbook.fetch_replies] user=%s listing=%s since_ts=%s -> 0 replies",
        user_id,
        listing_id,
        since_ts,
    )
    return []
