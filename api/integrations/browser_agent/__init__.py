"""browser-use AI-agent runner over Browserbase remote browsers.

Replaces both the deleted Bright Data discovery layer and the brittle
Playwright marketplace drivers with a single natural-language LLM-driven
browser agent. The same per-user Browserbase Context handles BOTH
discovery (search marketplaces, scrape listings) AND negotiation (send
messages, fetch replies).

Modules:
- ``client.py`` — ``run_action()`` spawns a Browserbase headless session
  bound to the user's context, constructs a browser-use ``Agent`` over
  CDP, runs the natural-language task, returns the parsed output.
- ``actions.py`` — high-level helpers (``search_listings``,
  ``send_message``, ``fetch_replies``) that craft natural-language tasks
  designed to produce structured JSON the lifecycle code can consume.
"""

from api.integrations.browser_agent import actions, client

__all__ = ["client", "actions"]
