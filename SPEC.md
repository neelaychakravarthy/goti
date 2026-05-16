# Goti — Hackathon SPEC

> Canonical project context. `/ship-it`, `/debug`, `/pr-feedback`, and the agents all read from here. Edit this file when scope changes — never let the code drift from the spec.

## Project summary

Goti is pitched as a generic agentic negotiation platform — it prepares, role-plays, monitors, and recommends moves during a negotiation. The launch use case (and demo path) is deal hunting: a user types a goal in natural language ("standing desk under $250 in SF, no IKEA"), Goti discovers matching listings across multiple online marketplaces, and runs parallel auto-negotiation jobs against sellers — each gated by human-in-the-loop approval on every outbound message. The defining feature is cross-negotiation BATNA leverage: when Goti is negotiating with seller A, the agent uses the current state of its negotiations with sellers B, C, D for the same product as leverage in its drafted messages.

Pitched as a generic agentic negotiation platform with deal-hunting as the launch surface. Built under the hood as a focused deal-hunting negotiation tool.

## Event context

- **Hackathon:** Agent Forge AI Hackathon (AgentForge). Organized by The AI Builders (community), backed by Beta Capital + Llama Ventures (venture partners). Held in the SF Bay Area.
- **Time budget:** Submission deadline 4:30 PM same day after a 10 AM start. Time/scope tradeoffs are owned by the team — do not push back on scope with LLM-estimated time budgets.
- **Demo / submission requirements:**
  - Working AI agent or agent swarm solving a real-world problem
  - Built on the partner stacks (see Required sponsors below)
  - Deployed live by demo time — no localhost demos
  - Live demo to judges
  - Judging dimensions: Completeness, Innovation, Real-Life Problem Solving, Sponsored Product Usage

## Required sponsors / integrations

All seven below are load-bearing for the Sponsored Product Usage criterion. Each has a concrete, non-cosmetic role in the agent topology — judges should see each one doing real work in the demo.

- **AgentField** (open-source AI backend) — Hosts the agent topology: discovery, valuation, negotiator, coordinator. Provides async execution, shared memory (used for BATNA cross-leverage), and the `app.pause()` HITL primitive for per-message approval. **Integration depth:** ≥4 reasoner agents defined with decorators; shared memory used as the cross-negotiation state bus; pause/resume drives every approval card in the UI.
- **Actionbook** (browser action engine) — Drives the user's logged-in Facebook Marketplace + Nextdoor sessions for outbound message sending. **Integration depth:** at least one negotiation round-trip per platform completed live in the demo via Actionbook's browser-driven flow.
- **Bright Data** (web scraping) — Discovery layer. Aggregates listings from FB Marketplace, Nextdoor, OfferUp, Craigslist for the listing view. **Integration depth:** Bright Data marketplace scrapers used to populate the discovery feed; ≥3 marketplaces shown in the demo.
- **EverOS / Evermind** (memory OS) — Stores Cases (completed negotiations) and surfaces Skills (learned negotiation patterns by category + region) before the negotiator drafts. **Integration depth:** Cases persisted per completed negotiation; ≥1 extracted Skill displayed in the demo's "learning loop" moment. Pre-seed with simulated past negotiations so the Memory Bank has content from minute zero.
- **Z.AI (GLM-5.1)** (frontier LLM) — Primary reasoning model for negotiator + coordinator agents. **Integration depth:** GLM-5.1 used for negotiation drafts; Claude via TokenRouter as fallback if GLM struggles on tone-sensitive drafts.
- **Zeabur** (deployment) — Deployment target for the full stack. Prefer Zeabur's AI app template (VTZ4FX referenced in the sponsor docs). Frontend on Vercel is the documented fallback if the Next.js + FastAPI + Postgres shape doesn't fit Zeabur cleanly. **Integration depth:** Goti reachable at a public Zeabur URL by demo time.
- **TokenRouter** (model routing) — Gateway for the Claude fallback path; routes between GLM-5.1 and Claude based on agent / task. **Integration depth:** at least the Claude fallback flows through TokenRouter, demonstrating two model providers under one routing layer.

Sponsors intentionally NOT load-bearing in v1: Nosana, Qwen / QwenCloud, Qoder, Butterbase. Do not force these into the architecture diagram.

<!--
Each sponsor entry should capture:
- Sponsor name
- Minimum integration depth required to qualify
- Where in the codebase the integration lives (filled in after first /ship-it that touches it)
-->

## Deployment

- **Target:** **Split deploy.** Frontend (`web/`, Next.js) on Vercel. Backend (`api/`, FastAPI + AgentField + Postgres) on Zeabur (explore Zeabur AI app template VTZ4FX). Resolution of original Open Q1: a single-Zeabur deploy was deemed risky on time budget; the split is safer (Vercel has first-class Next.js DX; Zeabur cleanly hosts the Python API + Postgres).
- **Deploy command:**
  - `web/` (Vercel): `vercel deploy` (preview) / `vercel deploy --prod` (release)
  - `api/` (Zeabur): TBD — depends on Zeabur config (likely `git push zeabur main` or deploy via the Zeabur dashboard linked to the repo). Resolved on first `/ship-it` round that lands a working backend dev loop.
- **Required env vars / secrets** — allocated between the two deploys:
  - **Vercel (`web/`):**
    - `NEXT_PUBLIC_API_BASE_URL` (public URL of the Zeabur backend)
    - `NEXTAUTH_SECRET`
  - **Zeabur (`api/`):**
    - `Z_AI_API_KEY` (Z.AI / GLM-5.1)
    - `TOKENROUTER_API_KEY` (gateway for all LLM calls — wired from day 1)
    - `ANTHROPIC_API_KEY` (parked for future Claude swap via TokenRouter; not used in v1)
    - `BRIGHT_DATA_API_KEY` + `BRIGHT_DATA_ZONE`
    - `ACTIONBOOK_API_KEY` + `ACTIONBOOK_FB_PROFILE_ID` + `ACTIONBOOK_NEXTDOOR_PROFILE_ID`
    - `EVERMIND_API_KEY`
    - `DATABASE_URL` (Postgres on Zeabur)

## Tech stack

- **Frontend:** Next.js (App Router) + Tailwind CSS + shadcn/ui. UI quality is a stated priority — sleek + clean, control-plane shape (left rail: active negotiations list; main: per-job chat view with approval cards). Greyed-out "Full Autonomy" toggle per job as a vision marker (non-functional in v1).
- **Backend:** Python (FastAPI) co-located with AgentField agents. Single Python codebase for the glue API + agent definitions.
- **Database / storage:** Postgres on Zeabur for app state (users, active negotiation jobs, message threads, approval queue, scraped listings cache). EverOS handles agent memory (Cases + Skills) separately.
- **Auth:** App-level login (single demo user for the hackathon) + per-user Actionbook browser profile holding FB Marketplace + Nextdoor sessions. Lightweight auth; not the focus.
- **AI / LLM:** **GLM-5.1 via Z.AI** for all agents in v1. **TokenRouter is wired as the LLM gateway from day one** — every model call goes through TokenRouter, even though v1 routes 100% of traffic to GLM. This satisfies TokenRouter's sponsor integration depth (real usage, not just a dependency line) and makes a future Claude swap a config change instead of a code change. No runtime routing logic in v1 — if GLM struggles on tone-sensitive drafts during dev, swap models manually via the TokenRouter config.

## MVP acceptance criteria

> The *minimum* shape the demo needs by submission. Each `/ship-it` increment moves one of these closer to ✅. When they're all ✅, the MVP is hit.

- [ ] Single demo user logs in to the Goti dashboard
- [ ] User types a natural-language goal; one fixed clarifying question (budget) asked
- [ ] Bright Data pulls listings from ≥3 marketplaces (including FB Marketplace + Nextdoor); they render as cards in the dashboard
- [ ] User clicks "Negotiate" on ≥2 listings; each spawns an async AgentField negotiation job
- [ ] Per-job chat view shows pending agent recommendations as approval cards; user approves to send
- [ ] Approved messages dispatch via Actionbook through the user's FB Marketplace or Nextdoor session
- [ ] Teammate-as-seller round-trip works: seller reply arrives in chat view; agent drafts counter using BATNA leverage from the other active negotiation; user approves; counter sent
- [ ] At least one negotiation closes on stage with an agreed price
- [ ] EverOS Memory Bank view shows new Cases populated from live demo negotiations + ≥1 extracted Skill (no pre-seed in v1; demo script must run ≥2 full negotiations before the Memory Bank moment so Skill extraction has enough live data to feel real)
- [ ] Greyed-out "Full Autonomy" toggle visible on each job (vision marker, non-functional)
- [ ] Deployed live at a public URL by submission time

## Out of scope

> Things the team is explicitly NOT building. Prevents scope creep. `/ship-it` populates as increments surface adjacent work that isn't part of MVP.

- Full-autonomy bypass (greyed-out toggle only — vision marker)
- WhatsApp / SMS / mobile-app interface (web dashboard only)
- Product-type-aware clarifying-question generation (single fixed budget Q)
- Negotiation strategy capture beyond budget (no aggressive/passive style controls)
- Payment coordination (stop at "deal agreed at $X, meet at <location>")
- Multi-user / team accounts (single demo user)
- OfferUp + Craigslist live negotiation round-trip (Bright Data may surface their listings for discovery breadth; Actionbook drives only FB + Nextdoor)
- Sponsors not in the v1 stack: Nosana, Qwen, Qoder, Butterbase

## Open questions

> Unresolved decisions. `/ship-it` re-surfaces these before round 2 of relevant increments.

- **Demo seller coordination** — how many teammates play sellers on second laptops, with what pre-posted listings? Deferred during kickoff: figure out after Streams B + C have a working end-to-end round-trip. Tracked against Stream C's "first real Actionbook send + reply" milestone.

> **Decisions resolved during `/kickoff --start` (2026-05-16):**
>
> - **Zeabur AI template VTZ4FX feasibility** → resolved: split deploy (Vercel for `web/`, Zeabur for `api/` + Postgres). See Deployment section.
> - **GLM → Claude routing** → resolved: TokenRouter wired as the LLM gateway from day one; 100% routed to GLM in v1; Claude swap is a config change. No runtime routing logic. See Tech stack AI/LLM.
> - **EverOS pre-seed** → resolved: skip pre-seed; Memory Bank populates from live demo negotiations only. See MVP acceptance criteria.
> - **Actionbook session capture flow** → resolved: build the real Actionbook session-import flow. UX details owned by Stream C during first `/ship-it` round on integrations.

## Other hard constraints

**Parallel team development.** Multiple teammates need to pick a part and develop + test it on their local machine independently before merging to the main branch.

Architectural implications:

- Module boundaries must be clean and decomposable. Suggested split: frontend dashboard / FastAPI glue layer / AgentField agents / Bright Data discovery / Actionbook FB driver / Actionbook Nextdoor driver / EverOS integration. One module per dev.
- External integrations need mockable seams — a frontend dev builds against fake listings, an Actionbook dev builds against a fake LLM, etc. No teammate is blocked because another teammate's integration isn't done.
- Local dev environment must run end-to-end without real API calls — `docker compose` for Postgres + FastAPI + Next.js, plus a mocked-externals mode for Bright Data / Actionbook / EverOS / TokenRouter.
- Standard git feature-branch workflow with merge to main.

`/ship-it` should plan increments along these module boundaries so parallel work is the default.

## Parallel workstreams

> Three teammates, each running their own Claude Code session against this harness. Each stream owns a self-contained slice and unblocks the others via mock seams. Cross-stream coordination happens through the interface contracts below — if you change a contract, post in team chat before merging so the other streams' mocks stay in sync.

### Stream A — Frontend + UX

**Owns:** `web/` (Next.js App Router).

**Scope:**
- Single-demo-user auth shell (NextAuth or equivalent; login → dashboard)
- Goal input + budget clarifying-question UI
- Listings grid (cards rendering discovery results)
- Per-job chat view (sent + received messages; pending approval card at the top)
- Approve / reject controls on each draft (with optional edit-before-send)
- Memory Bank view (Cases timeline + extracted Skills sidebar)
- "Link Facebook Marketplace" / "Link Nextdoor" buttons in onboarding (UI shell calls Stream C's session-import endpoints)
- Greyed-out "Full Autonomy" toggle per job (vision marker, non-functional in v1)
- Tailwind + shadcn/ui styling — control-plane shape: left rail (active negotiations list), main (per-job chat view)

**Develops against:** mocked REST API (static JSON fixtures matching the A↔B contract below). Frontend never talks to AgentField, Bright Data, or Actionbook directly.

**First `/ship-it` increment:** App shell + login + dashboard skeleton + goal input form, all wired to a mock-API JSON file. End state: a teammate logs in, types a goal, sees hardcoded listing cards, clicks one, sees a fake chat thread with an approval card.

**Sponsor depth owned by Stream A:** none directly (UI is the demo surface but no sponsor SDK lives in `web/`).

---

### Stream B — Agents + AI + Memory

**Owns:** `api/` (FastAPI + AgentField agents).

**Scope:**
- FastAPI REST + SSE/WebSocket endpoints (contract below)
- AgentField topology: discovery, valuation, negotiator, coordinator agents (≥4 reasoners with decorators)
- Shared memory as the cross-negotiation BATNA state bus
- `app.pause()` HITL primitive driving every approval card
- All LLM calls routed through TokenRouter (100% to GLM-5.1 in v1)
- EverOS integration: Cases written on negotiation completion; Skills read before the negotiator drafts
- Postgres models for jobs, threads, approval queue (schema co-owned with Stream C)

**Develops against:** mocked externals (`api/mocks/discovery.py`, `api/mocks/actionbook.py`) so agents run without real Bright Data or Actionbook calls. `GOTI_USE_MOCKS=1` env-var flips it.

**First `/ship-it` increment:** FastAPI hello-world + 1 AgentField reasoner agent + 1 GLM call through TokenRouter + stub endpoints returning hardcoded JSON matching the API contract. End state: `curl localhost:8000/api/goals` returns the same shape Stream A is mocking; one agent runs end-to-end against GLM and writes a stubbed Case.

**Sponsor depth owned by Stream B:** AgentField (≥4 reasoners + shared memory + pause/resume), Z.AI (GLM-5.1), TokenRouter (gateway for every LLM call), EverOS (Cases + Skills wiring).

---

### Stream C — External integrations + data

**Owns:** `api/integrations/` (Bright Data, Actionbook) + Postgres schema + `api/mocks/` fixtures.

**Scope:**
- **Bright Data discovery:** scrapers for FB Marketplace, Nextdoor, OfferUp, Craigslist. Aggregated into a uniform `Listing` shape. ≥3 marketplaces shown in demo.
- **Actionbook FB Marketplace driver:** send message + fetch replies for a listing thread.
- **Actionbook Nextdoor driver:** same, for Nextdoor.
- **Real Actionbook session-import flow** (resolution of original Open Q4): implement whatever Actionbook's session-capture API offers so a Goti user can link their FB / Nextdoor account. Owns the `POST /api/integrations/{provider}/link` endpoint that Stream A's UI buttons call. Investigate Actionbook's API in first round; document the chosen approach in SPEC.md then.
- **`GOTI_USE_MOCKS=1` env-var gate** that swaps real integrations for deterministic fixtures so Streams A + B can develop offline.
- **Postgres schema + migrations** for: users, integration_accounts (FB / Nextdoor session refs), listings_cache, jobs, message_threads, approval_queue.

**Develops against:** real Bright Data + Actionbook APIs for end-to-end smoke tests; rely on its own mock fixtures during iteration to avoid burning credits.

**First `/ship-it` increment:** Bright Data fetch for 1 marketplace + 1 query → returns `Listing[]` in the agreed shape. Actionbook FB driver sends 1 message + reads 1 reply against a test thread. Mock-externals module exposes the same interface with hardcoded responses. Postgres schema lands: users, integration_accounts, listings_cache tables (migrations checked in).

**Sponsor depth owned by Stream C:** Bright Data (≥3 marketplaces in demo), Actionbook (FB + Nextdoor drivers + real session-import).

---

### Cross-stream interface contracts

**A ↔ B (REST + SSE).** Stream B owns the contract; Stream A consumes it.

| Method | Path                                              | Purpose                                                                 |
|--------|---------------------------------------------------|-------------------------------------------------------------------------|
| POST   | `/api/goals`                                      | Submit a NL goal → `{goal_id, clarifying_question}`                     |
| POST   | `/api/goals/{goal_id}/clarify`                    | Submit budget → kicks off discovery → `{listings: [...]}`               |
| GET    | `/api/goals/{goal_id}/listings`                   | Re-fetch listings for a goal                                            |
| POST   | `/api/listings/{listing_id}/negotiate`            | Start async negotiation job → `{job_id}`                                |
| GET    | `/api/jobs`                                       | List active jobs for the demo user                                      |
| GET    | `/api/jobs/{job_id}`                              | Job state: messages, pending approval card, status                      |
| GET    | `/api/jobs/{job_id}/stream`                       | SSE: live updates (new draft, seller reply, status change)              |
| POST   | `/api/jobs/{job_id}/approvals/{card_id}`          | Approve / reject draft; body `{decision: "approve"\|"reject", edited_text?}` |
| GET    | `/api/memory/cases`                               | Memory Bank: list Cases                                                 |
| GET    | `/api/memory/skills`                              | Memory Bank: extracted Skills                                           |
| POST   | `/api/integrations/{provider}/link`               | "Link account" flow; provider ∈ {fb, nextdoor}                          |
| GET    | `/api/integrations`                               | List linked integrations for the demo user                              |

**Shared types** live in `api/contracts.py` (Pydantic) and `web/types.ts` (TypeScript — hand-mirrored or generated, pick one early in Stream A's first round): `Listing`, `Job`, `ApprovalCard`, `Message`, `Case`, `Skill`, `IntegrationAccount`.

**B ↔ C (Python).** Stream C owns these signatures; Stream B consumes them:

```python
# api/integrations/discovery.py
def search(query: str, marketplaces: list[str], max_per_source: int = 10) -> list[Listing]: ...

# api/integrations/actionbook/fb.py
def send_message(profile_id: str, listing_id: str, message_text: str) -> MessageId: ...
def fetch_replies(profile_id: str, listing_id: str, since_ts: float) -> list[Reply]: ...

# api/integrations/actionbook/nextdoor.py
def send_message(profile_id: str, listing_id: str, message_text: str) -> MessageId: ...
def fetch_replies(profile_id: str, listing_id: str, since_ts: float) -> list[Reply]: ...
```

`GOTI_USE_MOCKS=1` flips all three modules to `api/mocks/*.py` fixtures. Stream B sets this in local dev; Stream C maintains the fixtures next to the real implementations.

**A ↔ C:** no direct calls. UI → REST (B) → Python (C).

---

### Coordination notes

- **Contract changes** — if you change a JSON shape or function signature, post in team chat before merging. Other streams may be mocking against the old shape.
- **Branch model** — each stream on its own feature branch (`stream/a-frontend`, `stream/b-agents`, `stream/c-integrations`); merge to `main` via PR. Use `/pr-feedback` for review.
- **Push cadence** — hackathon-pace, but aim to push to `main` every ~90 min so other streams pull contract updates.
- **Deploy ownership** — Stream A owns the Vercel deploy (`web/`). Streams B + C share the Zeabur deploy (`api/` + Postgres).
- **Sponsor cross-checks** — each stream's sponsor depth is listed in its section above. Submission-load-bearing — verify per increment via `/ship-it`'s implementor "Sponsor / integration check."
