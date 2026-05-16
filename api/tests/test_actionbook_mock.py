"""Mock-path coverage for the Actionbook drivers (fb + nextdoor).

Live-path tests deferred to the round that implements the real Actionbook
API after the session-import spike.
"""

import pytest

from api.contracts import Reply
from api.integrations.actionbook import fb, nextdoor


pytestmark = pytest.mark.usefixtures("use_mocks")


async def test_fb_send_message_returns_counter_message_id():
    msg_id = await fb.send_message("profile-123", "listing-456", "Hello!")
    assert msg_id.startswith("mock-fb-msg-")
    # second send increments counter
    msg_id_2 = await fb.send_message("profile-123", "listing-456", "Hi again")
    assert msg_id != msg_id_2


async def test_fb_fetch_replies_returns_canned_seller_messages():
    replies = await fb.fetch_replies("profile-123", "listing-456", since_ts=0.0)
    assert len(replies) >= 1
    assert all(isinstance(r, Reply) for r in replies)
    assert all(r.sender == "seller" for r in replies)


async def test_nextdoor_send_message_returns_counter_message_id():
    msg_id = await nextdoor.send_message("profile-123", "listing-456", "Hi")
    assert msg_id.startswith("mock-nd-msg-")


async def test_nextdoor_fetch_replies_returns_canned_seller_messages():
    replies = await nextdoor.fetch_replies("profile-123", "listing-456", since_ts=0.0)
    assert len(replies) >= 1
    assert all(r.sender == "seller" for r in replies)
