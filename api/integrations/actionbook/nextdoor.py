"""Actionbook Nextdoor driver.

Real path is stubbed pending the Actionbook session-import spike (SPEC.md
Open questions). Mock path is in api/mocks/actionbook.py and is fully
functional for offline dev — set GOTI_USE_MOCKS=1.
"""

from api.config import get_settings
from api.contracts import MessageId, Reply

_SPIKE_MESSAGE = (
    "Actionbook real path not wired yet; the follow-up convergence increment "
    "rewires this onto Stream B's MCP `call_tool` seam. Set GOTI_USE_MOCKS=1 "
    "to develop against the mock fixtures in api/mocks/actionbook.py."
)


async def send_message(
    profile_id: str,
    listing_id: str,
    message_text: str,
) -> MessageId:
    if get_settings().use_mocks:
        from api.mocks.actionbook import nextdoor_send_message

        return await nextdoor_send_message(profile_id, listing_id, message_text)
    raise NotImplementedError(_SPIKE_MESSAGE)


async def fetch_replies(
    profile_id: str,
    listing_id: str,
    since_ts: float,
) -> list[Reply]:
    if get_settings().use_mocks:
        from api.mocks.actionbook import nextdoor_fetch_replies

        return await nextdoor_fetch_replies(profile_id, listing_id, since_ts)
    raise NotImplementedError(_SPIKE_MESSAGE)
