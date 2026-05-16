"""Actionbook FB Marketplace driver.

Real path is stubbed pending the Actionbook session-import spike (SPEC.md
Open questions). Mock path is in api/mocks/actionbook.py and is fully
functional for offline dev — set GOTI_USE_MOCKS=1.
"""

from api.contracts import MessageId, Reply
from api.settings import settings

_SPIKE_MESSAGE = (
    "Actionbook real path not wired yet; pending the session-import spike "
    "tracked in SPEC.md Open questions. Set GOTI_USE_MOCKS=1 to develop "
    "against the mock fixtures in api/mocks/actionbook.py."
)


async def send_message(
    profile_id: str,
    listing_id: str,
    message_text: str,
) -> MessageId:
    if settings.use_mocks:
        from api.mocks.actionbook import fb_send_message

        return await fb_send_message(profile_id, listing_id, message_text)
    raise NotImplementedError(_SPIKE_MESSAGE)


async def fetch_replies(
    profile_id: str,
    listing_id: str,
    since_ts: float,
) -> list[Reply]:
    if settings.use_mocks:
        from api.mocks.actionbook import fb_fetch_replies

        return await fb_fetch_replies(profile_id, listing_id, since_ts)
    raise NotImplementedError(_SPIKE_MESSAGE)
