# CLAUDE.md — Goti

## Project context

This is a hackathon project. See [`SPEC.md`](SPEC.md) for what we're building, sponsors, deployment target, and tech stack. **Always read `SPEC.md` first** when starting a session — its "Required sponsors / integrations" and "Deployment" sections are submission-load-bearing.

## Build / run / test / deploy

> Filled in by `/kickoff` from the tech-stack interview. Update these as the project evolves.

- **Install:** see README; multi-component install. Frontend: `cd web && npm install`. Backend: `cd api && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.
- **Run dev:** `docker compose up` (full stack) — or `cd web && npm run dev` (frontend only) / `cd api && uvicorn main:app --reload` (backend only). Exact compose file lands with the first `/ship-it` increment.
- **Test:** `cd api && GOTI_USE_MOCKS=1 pytest` (default — skips `live`-marked tests). Real Bright Data smoke: `cd api && pytest -m live -k test_discovery_live` (needs `BRIGHT_DATA_API_KEY` + `BRIGHT_DATA_FB_DATASET_ID` in shell).
- **Lint / typecheck:** TBD — populated by the first `/ship-it` increment that adds linting.
- **Build (deployable state check):** `docker compose up -d postgres && cd api && source .venv/bin/activate && alembic upgrade head && GOTI_USE_MOCKS=1 pytest` — Postgres healthy + migrations apply + mock-path tests pass.
- **Deploy:** Split deploy — `web/` (Next.js) on Vercel (`vercel deploy [--prod]`); `api/` (FastAPI) + Postgres on Zeabur (explore AI app template VTZ4FX). See `SPEC.md` Deployment for the per-deploy env-var allocation.

## Git policy

**Never alter git state without explicit approval.** Prohibited without explicit request: `git stash`, `git reset`, `git checkout`, `git restore`, `git clean`, `git commit`, `git rebase`, `git cherry-pick`, force-push, branch rename / delete, amend. Read-only commands (`git log`, `git diff`, `git blame`, `git show`, `git status`) are always fine.

**Documented exceptions** (skills that explicitly perform git writes after their plan-approval gate):
- `/kickoff` Phase 4 — initial `git init` + first commit
- `/ship-it` Phase 6 — optional commit-after-verify with explicit approval
- `/debug` Phase 8 — optional commit-after-verify with explicit approval

**First push on a new branch:** use `git push -u origin <branch>` to set tracking. After that, plain `git push` works.

## Conventions

- **No drive-by refactors.** Increment scope is whatever the `/ship-it` (or `/debug`) plan said. Don't expand silently. The `implementor` agent enforces this — if you find yourself wanting to "clean this up while I'm here," report it as a follow-up instead.
- **Sponsor-required integrations are submission-load-bearing.** If you change one, re-read the relevant `SPEC.md` section before shipping the increment. The implementor's "Sponsor / integration check" section in its report covers this.
- **Hackathon time budget is real.** Prefer the simplest working solution over the cleanest one. Tech debt is okay if it's documented in `SPEC.md` "Out of scope" or "Open questions". The framing: ship the demo, document the debt.
- **Every increment leaves the project deployable.** Run the build / deploy command from the table above after every meaningful change. The implementor checks this automatically; you should too when editing manually.
- **No new dependencies without approval.** If a task seems to need a new package (npm / pip / cargo / etc.), surface it before adding — sometimes the standard library or an existing dep covers the use case.
- **Mockable seams everywhere.** Every external integration (Bright Data, Actionbook FB/Nextdoor, EverOS, GLM, TokenRouter) must have a mocked-externals mode so teammates can work locally in parallel without burning real API credits or relying on internet. See `SPEC.md` "Other hard constraints" for the full parallel-dev policy.

## Available skills

| Skill            | When                                                       |
|------------------|------------------------------------------------------------|
| `/ship-it`       | Plan + implement the next increment toward the MVP         |
| `/debug`         | RCA-first bug-fix loop when the root cause isn't known     |
| `/pr-feedback`   | Triage + address PR review comments (if using PRs)         |
| `/skill-create`  | Create a new project-local skill                           |
| `/agent-create`  | Create a new project-local subagent                        |
| `/onboarding`    | Re-read the harness walkthrough                            |
| `/kickoff --start` | On hackathon day, run this to `git init` + first commit  |

## Agent stack

| Agent              | Model  | Role                                                                          |
|--------------------|--------|-------------------------------------------------------------------------------|
| `context-gatherer` | sonnet | Phase-1 brief: SPEC.md + CLAUDE.md + recent activity + focus findings         |
| `investigator`     | opus   | Answer one narrow question with grounded findings + proposed decision         |
| `implementor`      | opus   | Scoped file edits per an approved plan. Writes code; no git mutations         |

**Discovery caveat:** custom agents load at Claude Code **session start**. Adding or editing a file under `.claude/agents/` does NOT hot-reload — restart the session.

(Skills hot-load. Edit a SKILL.md and the next `/<name>` invocation picks it up.)

## What NOT to do

- Edit code in chat without invoking a skill. Even tiny changes go through `implementor` for the audit trail + deployable-state check.
- Let `SPEC.md` drift from reality. Update it when scope changes.
- Push without explicit confirmation.
- Skip the deployable-state check. Every increment must leave the project demoable.
- Forget sponsor requirements. SPEC.md has them — the implementor verifies per increment.
- Push back on scope using LLM-estimated time budgets. The team owns time/scope tradeoffs. Architectural / dependency / sponsor / risk pushback is welcome; "you don't have time for this" is not.
