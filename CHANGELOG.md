# Changelog

All notable changes to Goti are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Dates are ISO-8601.

## [0.1.0] — 2026-05-17

The first public release.

### Highlights

- **Agentic negotiation control plane.** Type a natural-language goal,
  Goti runs a long-running hunt lifecycle: clarifies budget, discovers
  listings across four marketplaces, ranks them, opens parallel
  negotiation jobs with cross-deal BATNA leverage, drafts every
  outbound message, and pauses for your approval at every send + every
  counter.
- **Six integrations.** AgentField (4 reasoners + shared memory +
  `app.pause()`), Anthropic Claude (every reasoner + every browser-use
  step), EverOS (Cases + Skills + extraction trigger), Browserbase +
  browser-use (per-user Contexts + AI browser loop), Zeabur + Vercel
  (split deploy).
- **Multi-tenant.** Google sign-in (NextAuth + JWT-bearer), per-user
  data isolation, onboarding checklist, rate limiting, CORS.

### Added

- Google OAuth sign-in via NextAuth (Auth.js v5); per-user data
  isolation across every table.
- Onboarding checklist: link Facebook Marketplace + Nextdoor via
  Actionbook OAuth (Clerk RFC 7591 dynamic client registration + PKCE
  S256).
- 5 AgentField reasoners (clarifier, valuation, negotiator,
  coordinator, picker) running on a shared `Agent(node_id="goti")`
  with shared `app.memory` BATNA state bus and native `app.pause()`
  HITL approvals via the FastAPI bridge router.
- Hunt orchestration: async background lifecycle (`run_hunt_lifecycle`)
  with 4 phases (clarify / discover+value / pick / negotiate) and
  per-job parallel sub-lifecycles.
- Durable hunt-lifecycle resumption via the `hunts.lifecycle_phase`
  column — a container restart re-spawns the right phase based on
  persisted side-effects (budget, listings_cache, jobs).
- Per-job lifecycle (`run_job_lifecycle`): draft + pause for approval
  → send via Actionbook → poll for seller reply → loop with BATNA
  threaded into the next draft → close-condition detection writes a
  Case to EverOS.
- Server-Sent Events notification stream
  (`GET /api/notifications/stream`) backed by an in-memory pub/sub
  queue + Postgres durability.
- Frontend notifications context: `ActivityBell`, per-kind toast, nav
  routing to `/start` / `/compare` / `/deal/:id`.
- Real Actionbook OAuth + MCP-over-HTTP JSON-RPC client with session
  caching + 401-refresh-retry.
- Actionbook tool catalog auto-populated on OAuth callback; FB and
  Nextdoor drivers look up real tool names instead of guessing.
- EverOS Skill extraction triggered after each Case write via
  `client.v1.memories.agent.flush(user_id, session_id)`.
- Anthropic Claude for every LLM call — reasoners (`api/llm.py`) and
  browser-use's per-step Agent loop both consume the same key.
  `CLAUDE_MODEL_ID` (default Haiku 4.5) covers the cheap reasoner calls;
  `CLAUDE_BROWSER_MODEL_ID` (default Sonnet 4.6) handles the larger
  `AgentOutput` schema browser-use forces via tool calls.
- Live reasoning timeline on the hunt detail page — every browser-agent
  step (discovery, send, fetch) is persisted to `hunt_activity_events`
  via `register_new_step_callback` and surfaced through
  `GET /api/hunts/{id}/activity`. The UI polls every 3 seconds so the
  user can watch the agent think.
- `GET /api/healthz` + `GET /api/readyz` liveness / readiness probes
  for production monitoring.
- Repo hygiene: LICENSE, CONTRIBUTING.md, SECURITY.md, CHANGELOG.md,
  PR + issue templates, VERCEL.md + ZEABUR.md deploy guides.

### Hardening

- CORS via `GOTI_ALLOWED_ORIGINS` env (comma-separated origins).
- Rate limiting via slowapi on `POST /api/goals`, OAuth init, and
  approval clicks.
- Startup env warnings for missing API keys so deployers can diagnose
  misconfiguration without spelunking endpoints.

### Changed

- Backend tests no longer require `GOTI_USE_MOCKS=1`. The mock layer
  was removed; integrations graceful-degrade when keys are missing,
  and tests stub at the HTTP / SDK boundary.

### Removed

- Single-demo-user model (replaced by multi-tenant Google sign-in).
- `web/lib/auth.ts` deprecated stub.
- Orphan UI components (`discovery-feed`, `discovery-status-line`,
  `preview-empty-state`) and unused types (`StackPreviewMini`,
  `BuyingRequest`).

### Project structure

- `api/` — FastAPI backend + AgentField reasoners (single Python
  codebase; the agent server runs as an in-process sidecar).
- `web/` — Next.js 16 frontend with NextAuth Google OAuth.
- Split deploy: Vercel (frontend) + Zeabur (backend + Postgres).
