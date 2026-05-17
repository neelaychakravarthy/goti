# Goti

> **Your agent that negotiates parallel deals on Facebook Marketplace,
> Nextdoor, OfferUp, and Craigslist — with you approving every send.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Status: production v0.1.0](https://img.shields.io/badge/status-v0.1.0-green.svg)](./CHANGELOG.md)
[![Frontend: Vercel](https://img.shields.io/badge/frontend-Vercel-black.svg)](./VERCEL.md)
[![Backend: Zeabur](https://img.shields.io/badge/backend-Zeabur-purple.svg)](./ZEABUR.md)

Type a goal in plain English — _"standing desk under $250 in SF, no
IKEA"_ — and Goti runs the full deal-hunt loop on your behalf:
discovers listings across four marketplaces, ranks them, opens parallel
negotiations, drafts every outbound message, and pauses for your
approval at every send and every counter. The defining feature is
**cross-negotiation BATNA leverage**: while negotiating with seller A,
the agent references the live state of negotiations with sellers B, C,
D for the same item.

## Status

Production v0.1.0 — multi-tenant Google sign-in, 5 external integrations
live (AgentField, Anthropic Claude, EverOS, Browserbase + browser-use,
Zeabur + Vercel), durable hunt lifecycle resumption.

## Live demo

→ **https://goti.vercel.app** _(set your own URL after deploying)_

## Quickstart (local)

Two terminals — backend in Docker, frontend via `npm run dev` (for fast
Turbopack hot-reload).

```bash
git clone https://github.com/neelaychakravarthy/goti.git && cd goti

# Backend env (read by docker-compose for the api + postgres services)
cp .env.example .env   # fill: ANTHROPIC_API_KEY, GOOGLE_OAUTH_CLIENT_ID
                       # (everything else is optional for first boot)

# Frontend env (Next.js reads from web/ — separate from the backend .env)
cp web/.env.local.example web/.env.local
# fill: NEXTAUTH_SECRET (run `openssl rand -base64 32`),
#       GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET (from Google Cloud Console),
#       NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID (same value as the client id)
```

**Set up Google OAuth credentials.** Go to
[Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
→ *Create OAuth 2.0 Client ID* → Application type: *Web*. Set the
authorized redirect URI to `http://localhost:3000/api/auth/callback/google`.
Copy the client ID + secret into `web/.env.local` AND the client ID into
the backend `.env` (same value on both sides).

**Terminal 1 — backend** (Postgres + FastAPI + AgentField agent server):

```bash
docker compose up --build
# postgres :5432 · api :8000 · agent server :8080 (loopback)
```

**Terminal 2 — frontend** (Next.js dev server):

```bash
cd web
npm install
npm run dev
```

Open http://localhost:3000. Sign in with Google, complete the onboarding
checklist (link Facebook Marketplace + Nextdoor via Browserbase Live
View), then type your first hunt.

## How it works

```
USER TYPES GOAL
    │  POST /api/goals
    ▼
Hunt row created → asyncio.create_task(run_hunt_lifecycle(hunt_id))
    │
    ▼
Phase 1: clarifier reasoner pauses for budget  ───────┐
Phase 2: discovery + valuation reasoners run          │
Phase 3: picker reasoner pauses for picks  ───────────┤  app.pause() →
Phase 4: per-listing negotiator reasoner pauses       │  AgentField bridge →
         for each draft + each counter  ──────────────┘  POST /api/v1/agents/goti/.../request-approval
                                                            │
                                                            ▼
                                              Creates approval_queue + Notification rows
                                                            │
                                                            ▼
                                              Pushes to in-memory asyncio.Queue
                                                            │
                                                            ▼
                                              GET /api/notifications/stream (SSE)
                                                            │
                                                            ▼
                                              Frontend EventSource → React state →
                                              ActivityBell + toast + nav routing

User decides → POST /api/approvals/{approval_request_id}
    │  body: { decision, feedback }
    ▼
Bridge POSTs to agent's /webhooks/approval
    │
    ▼
Reasoner's app.pause() returns → reasoner continues → lifecycle advances
```

See [CHANGELOG.md](./CHANGELOG.md) for the per-release feature
breakdown, including the async architecture, the per-job loop, durable
resumption via `hunts.lifecycle_phase`, and the multi-tenant shape.

## Integration stack

| Integration | Role | Where it lives |
|---|---|---|
| [AgentField](https://agentfield.com/) | Hosts the agent topology (5 reasoners + shared memory + `app.pause()` HITL) | `api/agents/`, `api/routes/agent_bridge.py` |
| [Anthropic Claude](https://www.anthropic.com/) | LLM for every reasoner + every browser-use Agent step | `api/llm.py`, `api/integrations/browser_agent/client.py` |
| [EverOS / Evermind](https://www.evermemos.com/) | Cases (negotiation transcripts) + Skill extraction trigger | `api/memory_store.py` |
| [Browserbase](https://browserbase.com/) + [browser-use](https://browser-use.com/) | Remote-browser infrastructure (per-user Context) + AI agent that reasons through marketplace DOMs — drives BOTH discovery (search) AND negotiation (send / fetch) | `api/integrations/browserbase/`, `api/integrations/browser_agent/` |
| [Zeabur](https://zeabur.com/) + [Vercel](https://vercel.com/) | Backend + frontend deploys | `zeabur.toml`, `web/` |

## Tech stack

- **Frontend:** Next.js 16 (App Router) + Tailwind CSS + shadcn/ui +
  NextAuth (Google OAuth).
- **Backend:** Python 3.11 + FastAPI + AgentField agents (in-process
  sidecar) + Postgres (async SQLAlchemy + Alembic).
- **Realtime:** Server-Sent Events for notifications + per-job state.
- **Auth:** Google ID token → backend verifies via JWKS → per-user
  data isolation across all tables.

## Deploy your own

Split deploy:

- **Frontend** → Vercel. Step-by-step in [VERCEL.md](./VERCEL.md).
- **Backend** (`api/` + Postgres) → Zeabur. Step-by-step in
  [ZEABUR.md](./ZEABUR.md).

Both files cover env vars, Google Cloud Console setup, and the
connection-test checklist.

## Development

```bash
# Backend
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend
cd web
npm install
npm run dev
```

### Tests

```bash
cd api
pytest -m "not live"   # default — unit + integration tests
```

### Health probe

```bash
curl http://localhost:8000/api/healthz
# {"status":"healthy","checks":{"db":"ok","anthropic_key":"ok",...}}
```

## Concurrency model

Discovery and negotiation jobs run as independent async coroutines —
streaming discovery iterates one listing at a time while any number of
negotiation jobs can be in flight in parallel (that's the BATNA story:
multiple open negotiations feed each other's drafts via the shared
conversation history). Each browser-use call (one search iteration,
one message send, one reply check) acquires a permit from an in-process
semaphore sized to your Browserbase tier's concurrent-browsers quota
(free=3, Developer=25, Startup=100) — set via `BROWSERBASE_MAX_CONCURRENT`.
On free tier with 3 permits you get one discovery slot running
alongside up to two parallel negotiations; bump the env var to your
plan's ceiling to scale up.

## Browserbase quotas (heads-up)

Browserbase enforces **two** quotas per plan that Goti users hit fast:

| Plan | Concurrent browsers | Monthly browser-minutes |
|---|---|---|
| Free | 3 | 60 |
| Developer | 25 | 1000 |
| Startup | 100 | unmetered |

Every browser-use Agent run consumes minutes — a single discovery
iteration is ~30–90s, a send/fetch step is ~30–60s. **You'll burn the
free-tier 60 minutes in roughly 30–60 actions across a few hunts.**
When that happens, Browserbase returns `402 Payment Required` on every
new session — Goti catches it, marks the hunt as error, emits a
`Browserbase quota exhausted` notification, and the onboarding tile
shows a dedicated "Upgrade Browserbase" banner with a link to
[browserbase.com/plans](https://browserbase.com/plans). The fix is on
Browserbase's side; bump your plan or wait for the monthly reset.

## Docker disk usage

The API image is ~1.5 GB (FastAPI + browser-use + playwright + the
AgentField agent server). What balloons after lots of development is
the **build cache** — every `docker compose up --build` writes a new
layer for the `pip install -r requirements.txt` step, and Docker keeps
old layers indefinitely for cache lookups. After dozens of rebuilds the
cache can hit 15+ GB.

Clear it without touching your images/containers/volumes:

```bash
docker builder prune -af
```

For an aggressive reset (also drops the postgres volume — wipes your
local DB):

```bash
docker compose down -v
docker system prune -af --volumes
```

The Dockerfile uses a 2-stage build (builder venv → runtime) so each
fresh layer is smaller — but rebuild cadence is still the main driver
of accumulated disk usage.

## Known limitations

- **Facebook Marketplace cookies are flaky.** Meta's anti-bot pipeline
  invalidates Browserbase-hosted sessions when the IP / fingerprint
  doesn't match the original login. Re-linking FB via the onboarding
  tile usually restores it for that session. Browserbase's
  `advancedStealth` + residential proxies fix this reliably but are
  Scale-tier features. Discovery on Craigslist + OfferUp works without
  login, so demos still work even if FB is logged out.

## Roadmap

See [CHANGELOG.md](./CHANGELOG.md) for shipped features. Near-term:

- Persist OAuth client registration (currently in-memory cache)
- Per-marketplace fetch-replies scheduler (replace 10s polling with
  push-style)
- Switch BATNA leverage to a real coordinator-LLM call (currently
  string-mixed)
- Mobile-responsive deal-room UI

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) — branch naming,
conventional commits, PR template.

## License

[MIT](./LICENSE) — © 2026 Neelay Chakravarthy.
