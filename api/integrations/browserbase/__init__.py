"""Browserbase integration.

Goti owns a single ``BROWSERBASE_API_KEY`` + ``BROWSERBASE_PROJECT_ID``;
each Goti user gets one Browserbase Context (``bb_ctx_*``) that persists
their FB Marketplace + Nextdoor cookies across sessions. The user's
initial login happens in a kept-alive Browserbase session opened in a
new browser tab via the Live View URL.

Subpackages:

- ``client`` — async wrapper around the ``browserbase`` Python SDK:
  ``create_context``, ``create_session_with_live_view``,
  ``create_headless_session``, ``end_session``, ``delete_context``.
- ``marketplaces.fb`` / ``marketplaces.nextdoor`` — Playwright drivers
  that connect over CDP to a Browserbase session and drive the
  marketplace UI for ``send_message`` + ``fetch_replies``.
"""

from api.integrations.browserbase import client

__all__ = ["client"]
