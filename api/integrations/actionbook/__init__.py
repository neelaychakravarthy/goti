"""Actionbook MCP+OAuth integration (Stream B-owned slice).

Exposes:
- ``oauth`` — Clerk OAuth flow helpers: dynamic client registration,
  PKCE-protected authorize URL building, code exchange, token refresh.
- ``client`` — MCP-over-HTTP JSON-RPC client with Bearer auth + session
  management, plus a high-level ``send_message`` helper used by
  ``api/routes/approvals.py`` when ``GOTI_USE_MOCKS=0``.
"""

from api.integrations.actionbook import client, oauth

__all__ = ["client", "oauth"]
