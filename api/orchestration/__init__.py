"""Orchestration package — job lifecycle + SSE + reasoner dispatch.

Wires the FastAPI routes (`api/routes/jobs.py`, `api/routes/approvals.py`,
`api/routes/goals.py`) to the AgentField reasoners (`api/agents/*`) and the
Postgres state (`api/models.py`).
"""
