"""External integration clients.

Subpackages:
- ``browserbase/`` — Browserbase Contexts + Sessions SDK wrapper. Owns
  per-user Context provisioning (one Context covers all marketplaces
  the user logged into) + Session creation (Live View for login,
  headless CDP for backend automation).
- ``browser_agent/`` — browser-use AI-agent runner over Browserbase
  remote browsers. The SAME context drives BOTH discovery (search
  marketplaces, scrape listings) AND negotiation (send messages, fetch
  replies) via natural-language tasks
  scrapers + the brittle Playwright selectors.
- ``discovery.py`` — thin dispatcher that resolves the user's
  Browserbase context_id + delegates to ``browser_agent.actions
  .search_listings``.
"""
