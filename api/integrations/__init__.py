"""External integration clients (Stream B + Stream C ownership split).

Stream B owns:
- ``actionbook/`` — MCP-over-HTTP client + Clerk OAuth flow (this module).

Stream C owns (not in this package yet):
- ``discovery.py`` — Bright Data discovery (see ``api/mocks/discovery.py`` for the
  contract).
- ``actionbook/fb.py`` + ``actionbook/nextdoor.py`` — marketplace-verb wrappers
  layered on top of Stream B's ``call_tool`` seam.
"""
