"""Stateless Actionbook mock for Stream B's offline dev loop.

send_message: returns a counter-based MessageId per provider. Counters are
module-level, so tests should not assert exact values across test boundaries.
fetch_replies: returns the same 1-2 hardcoded Reply rows per provider,
ignoring since_ts. Replies look like real marketplace seller messages so
Stream B's negotiator agent sees realistic input during dev.
"""

from __future__ import annotations

import time
from itertools import count
from typing import Iterator

from api.contracts import MessageId, Reply

# Per-provider counters; module-level so identical message-id values reset
# only on process restart. Adequate for dev loops; tests should assert on
# format (prefix + width) rather than exact integer.
_fb_counter: Iterator[int] = count(1)
_nextdoor_counter: Iterator[int] = count(1)

_NOW = time.time()

_FB_REPLIES: list[Reply] = [
    Reply(
        message_id=MessageId("mock-fb-reply-001"),
        listing_id="__any__",
        sender="seller",
        text="Still available. I'm pretty firm at $300 but I'll throw in the cable.",
        received_at=_NOW - 600,  # 10 min ago
    ),
    Reply(
        message_id=MessageId("mock-fb-reply-002"),
        listing_id="__any__",
        sender="seller",
        text="Honestly I can do $250 if you can pick up this evening.",
        received_at=_NOW - 60,  # 1 min ago
    ),
]

_NEXTDOOR_REPLIES: list[Reply] = [
    Reply(
        message_id=MessageId("mock-nd-reply-001"),
        listing_id="__any__",
        sender="seller",
        text="Hi neighbor! Yes still here. Price is $280 OBO.",
        received_at=_NOW - 1200,  # 20 min ago
    ),
    Reply(
        message_id=MessageId("mock-nd-reply-002"),
        listing_id="__any__",
        sender="seller",
        text="$240 works for me if you can grab it tomorrow morning.",
        received_at=_NOW - 30,
    ),
]


async def fb_send_message(
    profile_id: str, listing_id: str, message_text: str
) -> MessageId:
    return MessageId(f"mock-fb-msg-{next(_fb_counter):04d}")


async def fb_fetch_replies(
    profile_id: str, listing_id: str, since_ts: float
) -> list[Reply]:
    return list(_FB_REPLIES)  # defensive copy


async def nextdoor_send_message(
    profile_id: str, listing_id: str, message_text: str
) -> MessageId:
    return MessageId(f"mock-nd-msg-{next(_nextdoor_counter):04d}")


async def nextdoor_fetch_replies(
    profile_id: str, listing_id: str, since_ts: float
) -> list[Reply]:
    return list(_NEXTDOOR_REPLIES)  # defensive copy
