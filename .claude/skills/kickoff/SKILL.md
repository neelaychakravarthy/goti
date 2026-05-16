---
name: kickoff
description: Bootstrap a new hackathon project — split into two phases so the team can prep before the hackathon and start coding when it begins. Phase A (--spec-only) runs the interview and writes SPEC.md + CLAUDE.md + .claude/ harness install with NO git init. Phase B (--start) reads the existing spec, runs git init + first commit. Default (no flag) runs both phases in one go for teams that prep the day of. Plan-gated; zero assumptions on the interview.
trigger: /kickoff
---

# /kickoff

The first command a hackathon team runs. Bootstraps the project across one or two phases:

- **Phase A — spec prep (`--spec-only`)** — interviews you on what you're building, sponsors, deployment, tech stack, time budget. Writes `SPEC.md` + `CLAUDE.md` + scaffold files + installs `.claude/` harness. **Does NOT `git init`.** Use this before the hackathon starts, to plan in advance.
- **Phase B — hackathon start (`--start`)** — picks up the existing `SPEC.md`, confirms it's still accurate, runs `git init` + first commit. Optionally wires a remote. Use this when the hackathon actually begins.

Default behavior (no flag) runs both phases in one session — the right choice for teams that plan and start coding on the same day. Pass `--spec-only` if you're prepping ahead and want the git init to wait.

The `SPEC.md` this skill produces is the **single source of project context** for every downstream skill in this harness. `/ship-it`, `/debug`, `/pr-feedback`, and the agents all read it. The interview here is load-bearing — vague answers now mean vague plans later.

## Directory model

`/kickoff` is **invoked from this harness directory** (so Claude Code can read the skill), but the new project is created **somewhere else** — typically as a sibling of the harness directory, or at any absolute path you specify. The harness directory stays unchanged; the new project gets its own copy of the harness installed under `.claude/`.

Typical filesystem after running `/kickoff`:

```
~/
├── claude-code-hackathon/                 ← the harness (you run /kickoff from here)
│   ├── agents/, skills/, README.md, ...
│
└── <your-hackathon-project>/              ← created by /kickoff (sibling by default)
    ├── SPEC.md
    ├── CLAUDE.md
    ├── README.md
    ├── .gitignore
    ├── .env.example
    └── .claude/
        ├── agents/                        ← copied from the harness
        ├── skills/                        ← copied from the harness
        └── settings.json                  ← copied from the harness
```

The new project's `.claude/` is a **copy**, not a symlink — you can edit skills in the project without affecting the harness. Reciprocally, updates to the harness don't propagate automatically; if a teammate improves a skill in the harness, you `cp` the change in or re-run a future `/install`-style helper.

## Usage

```
/kickoff                             # interactive: full interview + scaffold + git init (one-shot)
/kickoff <dir>                       # one-shot, into <dir>
/kickoff --spec-only                 # Phase A: interview + scaffold, NO git init (use pre-hackathon)
/kickoff --spec-only <dir>           # Phase A, into <dir>
/kickoff --start                     # Phase B: read existing SPEC.md, do git init + first commit
/kickoff --start <dir>               # Phase B, against <dir> (or cwd if omitted)
/kickoff --continue                  # resume an interrupted interview
/kickoff --dry-run                   # full preview to a tmp dir; no real writes
```

`<dir>` may be:
- A path that does not yet exist → created.
- An existing empty directory → used as-is.
- An existing non-empty directory → guarded by `AskUserQuestion` (see Non-negotiable #2).
- For `--start`: must already exist and contain a populated `SPEC.md`.

## Non-negotiables

1. **Zero assumptions on the interview.** Every choice with ≥2 viable options surfaces as `AskUserQuestion` before scaffolding. Tech stack, deployment target, sponsor list, time budget, project name — all asked, never assumed. A "default" you'd write into SPEC.md anyway is still confirmed.
2. **Never overwrite an existing project without explicit approval.** If `<dir>` already contains files, fire `AskUserQuestion`: "Treat as existing project — adopt SPEC.md flow into it" / "Pick a different directory" / "Abort." Never silently clobber. Specifically: never delete existing files, never overwrite a pre-existing `SPEC.md` / `CLAUDE.md` / `README.md` without per-file confirmation.
3. **Never alter git state without explicit approval.** `git init`, initial commit, and any remote setup each sit behind their own `AskUserQuestion` gate inside Phase 4. `ExitPlanMode` approves direction, not writes.
4. **Plan-gated before any file write or git mutation.** `EnterPlanMode` + `ExitPlanMode` covers the scaffold plan. Per-action gates inside Phase 4.
5. **Interactive approvals use built-in tools.** `AskUserQuestion` / `EnterPlanMode` / `ExitPlanMode` — not inline markdown dumps. Batch up to 4 questions per `AskUserQuestion` call.
6. **The interview is the spec.** Whatever the team commits to here goes verbatim into `SPEC.md`. Downstream skills treat that file as canonical. Do not silently re-shape interview answers when writing the file.
7. **Sponsors are submission-load-bearing.** Hackathon prizes often depend on "must use Sponsor X's tech." When the team lists sponsors, capture exactly which Sponsor APIs / SDKs / services they're committing to, plus the minimum integration depth to qualify (e.g., "auth via Sponsor X" vs. "any API call to Sponsor X"). The implementor will need this to verify increments.

## Workflow

### Mode selection

`/kickoff` runs in one of three modes, decided by the flag:

- **Default (no flag)** — runs Phase 1 → 2 → 3 → 4 (all gates including git init) → 5. One-shot.
- **`--spec-only`** — runs Phase 1 → 2 → 3 → 4 (but **skips Gates 4.3 and 4.4** — no `git init`, no remote setup) → 5 (handoff message tailored for "come back with `--start` when the hackathon begins").
- **`--start`** — runs Phase 1.5 (read existing SPEC.md, confirm accuracy) → Phase 4 Gates 4.3 + 4.4 only (git init + optional remote) → Phase 5. Phases 2 and 3 are SKIPPED — the spec already exists. If `<dir>/SPEC.md` is missing, abort with a pointer at `--spec-only`.

### Phase 1 — Parse invocation + locate target directory

1. **Parse the invocation.** Extract `<dir>`, `--spec-only`, `--start`, `--continue`, `--dry-run`. If multiple of `--spec-only` / `--start` / `--continue` are passed, prefer the first detected and warn.

2. **Resolve target directory.**
   - If `<dir>` was supplied: use it. If it doesn't exist and mode != `--start`, plan to create it (gated in Phase 4). If `--start` and it doesn't exist: abort — "`--start` requires an existing project dir with a `SPEC.md`."
   - If no `<dir>`:
     - For `--start`: assume cwd is the project root and check for `<cwd>/SPEC.md`. If missing, `AskUserQuestion` for the project dir path.
     - For default / `--spec-only` / `--continue`: `AskUserQuestion` — "Where should I create the project?" Options:
       - "Create new dir as a sibling of this harness directory (Recommended — keeps the harness separate from your project)" — follow-up: ask for the project name (`AskUserQuestion`), use `<parent-of-cwd>/<name>/`.
       - "Specify a custom absolute path" — follow up: free-text.
       - "Use current cwd" — only valid if cwd is empty or `--continue`; otherwise guarded by Non-negotiable #2. Warn explicitly that this will install `.claude/` into the cwd, which is fine if cwd is a fresh project dir but **wrong if cwd is the `claude-code-hackathon` harness directory**.
   - If the target dir exists and is non-empty: fire the Non-negotiable #2 question before any read of its contents.

3. **`--continue` path:** if `<dir>/SPEC.md` exists and looks partially filled (has a `<!-- DRAFT — kickoff interview in progress -->` marker), skip to the section of the interview that wasn't completed. Otherwise treat as a fresh kickoff and warn.

### Phase 1.5 — `--start`-mode validation (skip if not `--start`)

Only run for `--start` mode. Skip otherwise.

1. **Read `<dir>/SPEC.md`.** If missing, abort: "No SPEC.md found at `<dir>/SPEC.md`. Run `/kickoff --spec-only <dir>` first to generate the spec, or `/kickoff <dir>` for a fresh one-shot kickoff."

2. **Display the spec summary** in chat — pull out the Project summary, Required sponsors, Deployment target, and MVP acceptance criteria sections. The team is about to start the hackathon — surface what they committed to before any git writes happen.

3. **`AskUserQuestion` — confirm spec is still accurate.** Options:
   - "Spec is accurate, proceed to git init (Recommended)"
   - "Spec needs minor edits — I'll make them inline now" — follow-up: dev edits SPEC.md via direct chat; the skill waits, re-reads SPEC.md, then re-fires this question.
   - "Spec needs significant rework — go back to interview" — restart at Phase 2 Round 1 with the existing SPEC.md as the starting point (each round's questions pre-fill from the existing file).
   - "Abort — I'm not ready."

4. **Verify the `.claude/` install is present** (`<dir>/.claude/agents/`, `<dir>/.claude/skills/`). If missing, `AskUserQuestion`: "The harness isn't installed at `<dir>/.claude/`. Options: Copy it from this harness directory now (Recommended) / Abort." Re-using the same copy logic as Gate 4.2.

5. Skip Phases 2 + 3. Jump directly to Phase 4 — but only Gates 4.3 (git init) + 4.4 (remote, optional) will run; Gates 4.1 and 4.2 are no-ops because the dir + files already exist.

### Phase 2 — Interview (3 rounds of `AskUserQuestion`, ≤4 questions per round)

Each round batches ≤4 questions. Use `preview` on options when comparing concrete artifacts (project-name candidates, stack templates). Mark the recommended option with "(Recommended)" only when there's a clear default — for many hackathon choices there isn't, so don't fake one.

**Round 1 — what + why:**

1. **Project name** — free text, but `AskUserQuestion` proposes 2–3 slug variants based on the team's free-text "what we're building" if they've already mentioned it. Otherwise free-text only.
2. **What are you building?** (1–3 sentences, free text) — this lands verbatim in `SPEC.md` "Project summary."
3. **Hackathon name + sponsor / org, if any** — free text. Used in `SPEC.md` "Event context." Some hackathon prize tracks have submission rules that affect tech-stack choice — flag these later if they emerge.
4. **Time budget** — options: "24 hours" / "48 hours" / "72 hours" / "weeklong" / "other (specify)". Determines how aggressive `/ship-it` should be about scoping increments.

**Round 2 — sponsors + integrations + deployment:**

5. **Required sponsor integrations** — multiSelect free-fill. After the dev names sponsors, fire a follow-up `AskUserQuestion` **per sponsor** (batch ≤4 per call):
   - "For sponsor `<X>`, what's the minimum integration depth required to qualify for their prize / track?"
   - Options: "Use their SDK / API for a specific feature (specify)" / "Any API call counts" / "Branding / mention only — no code integration" / "Not sure — I'll check their rules and report back". Capture the answer per-sponsor in `SPEC.md`.
6. **Deployment target** — multiSelect. Options should include the common hackathon targets plus an "other" path:
   - "Sponsor-specific (must deploy on Sponsor X's platform — specify which)"
   - "Vercel / Netlify (web app, static or SSR)"
   - "Cloudflare Workers / Pages"
   - "Fly.io / Render / Railway (container or buildpack)"
   - "AWS / GCP / Azure (specify service)"
   - "Self-hosted demo (ngrok or local laptop during judging)"
   - "Mobile app (TestFlight / APK)"
   - "Desktop / CLI / no deploy — just a runnable artifact"
   - "Other — I'll describe"
   Once selected, fire a follow-up `AskUserQuestion` capturing the **deploy command** (or "TBD — we'll figure it out") and any **environment / secret requirements** the team knows about up front. The deploy command goes in `SPEC.md`'s "Deployment" section; the implementor will treat it as the deployable-state check.
7. **Demo / submission requirements** — free text. What does the team need to have working at submission time? (e.g., "a public URL, a 3-min video, a one-pager"). Used by `/ship-it` to anchor MVP scope.

**Round 3 — tech stack + conventions:**

8. **Frontend** — options: "None (backend / CLI / agent only)" / "React + Vite" / "Next.js" / "SvelteKit" / "Vue" / "Plain HTML/JS" / "Mobile (React Native / Expo)" / "Other — I'll describe." Add `preview` snippets showing the stack's typical init command.
9. **Backend** — options: "None (frontend-only / serverless / sponsor-hosted)" / "Node.js (Express / Hono / Fastify)" / "Python (FastAPI / Flask)" / "Go (chi / stdlib)" / "Rust (Axum)" / "Other." Same `preview` pattern.
10. **Database / storage** — options: "None (in-memory / no persistence)" / "Sponsor-provided (e.g., Supabase / PlanetScale / Convex / Neon — specify)" / "SQLite (file-based)" / "PostgreSQL self-hosted" / "Redis / KV" / "Other."
11. **Auth** — options: "None (open demo)" / "Sponsor-provided (Clerk / Auth0 / Supabase / specify)" / "Hand-rolled (JWT, sessions — risky for 24h)" / "Magic link / OAuth via library" / "TBD — decide later." Flag "TBD" as a Phase-3 follow-up the team needs to resolve before `/ship-it` round 2.
12. **AI / LLM provider** (if relevant to the project) — options: "Anthropic Claude API" / "OpenAI" / "Sponsor-provided model" / "Local (Ollama / llama.cpp)" / "None — no AI" / "Multi-provider." If selected, follow up: which models exactly, and where do API keys come from?

After each round, restate the captured answers in a short bullet list in chat — no `ExitPlanMode` mid-interview (Phase 3's plan-mode gate covers everything). Give the dev one chance to correct any answer before moving to the next round.

**Round 3.5 — anything we missed (single open-ended `AskUserQuestion`):**

13. **Any other hard constraints we haven't covered?** Options: "Yes — I'll describe" (free text) / "No — proceed to plan". Common hackathon constraints: judging-time presence (need to be physically there), local-only demo (no public URL), data residency (region requirements), team-member specialization (one person owns backend, etc.).

### Phase 3 — Plan + approval gate

**Step 3.1 — Open questions check.**

Before plan mode, scan the captured interview for unresolved items: any "TBD" / "I'll check" / "Not sure" answers. Surface each as a new `AskUserQuestion`:
- "Resolve now — I'll answer" (free-text follow-up)
- "Defer to SPEC.md 'Open questions' — `/ship-it` will surface again on round 2"
- "Drop — not actually a constraint"

Items marked "Defer" land in `SPEC.md`'s "Open questions" section verbatim, so `/ship-it` re-surfaces them at the right moment.

**Step 3.2 — `EnterPlanMode` and write the kickoff plan.**

Plan file contents:

1. **Target directory** — `<absolute-path>` (created / existing-empty / existing-with-files).
2. **Files to create:**
   - `SPEC.md` — full body preview (the section structure below, populated from the interview).
   - `CLAUDE.md` — project-root rules (build / test / deploy commands, language pins, conventions to enforce, "what NOT to do" list).
   - `README.md` — minimal skeleton: project name, 1-line description, "run locally" placeholder.
   - `.gitignore` — populated from the chosen tech stack (`node_modules/`, `__pycache__/`, `.env`, `dist/`, `build/`, etc.).
   - `.claude/` subtree — `agents/`, `skills/`, `settings.json`, copied from this harness's source location.
   - `.env.example` — empty stub with placeholders for any sponsor API keys / database URLs the team mentioned.
3. **Git operations** (gated separately in Phase 4):
   - `git init` (only if `<dir>` is not already a git repo)
   - Initial commit `chore: kickoff scaffold`
   - Optional remote setup (asked separately — see Gate 4.4)
4. **Dev's next step:** `cd <dir>` and run `/ship-it` to plan the first increment.

**Preview the SPEC.md body** in the plan — first ~30 lines so the dev can read the captured interview verbatim. Don't dump the full file.

**SPEC.md shape** (this is the canonical structure — keep these headings even if a section is empty so downstream skills can find them):

```markdown
# <Project Name> — Hackathon SPEC

> Canonical project context. `/ship-it`, `/debug`, `/pr-feedback`, and the agents all read from here. Edit this file when scope changes — never let the code drift from the spec.

## Project summary

<from Round 1 Q2, verbatim>

## Event context

- **Hackathon:** <Round 1 Q3>
- **Time budget:** <Round 1 Q4>
- **Demo / submission requirements:** <Round 2 Q7>

## Required sponsors / integrations

<one bullet per sponsor — Round 2 Q5 + follow-up answers — including required integration depth>

## Deployment

- **Target:** <Round 2 Q6>
- **Deploy command:** <follow-up, or "TBD">
- **Required env vars / secrets:** <follow-up list, or None.>

## Tech stack

- **Frontend:** <Round 3 Q8>
- **Backend:** <Round 3 Q9>
- **Database / storage:** <Round 3 Q10>
- **Auth:** <Round 3 Q11>
- **AI / LLM:** <Round 3 Q12, including model + key source>

## MVP acceptance criteria

<the *minimum* shape the demo needs by submission — derived from Q7 + Q2; if the team hasn't defined this yet, write "TBD — define before first /ship-it round" and add to Open questions>

## Out of scope

<things the team is explicitly NOT building, to prevent scope creep — initially empty; /ship-it will populate as increments converge>

## Open questions

<one bullet per unresolved item from Phase 3 Step 3.1 + Round 3.5 — re-surfaced by /ship-it round 2>

## Other hard constraints

<Round 3.5 Q13 free text, or None.>
```

**CLAUDE.md shape** (the project-root rules file; small, opinionated):

```markdown
# CLAUDE.md — <Project Name>

## Project context

This is a hackathon project. See `SPEC.md` for what we're building, sponsors, deployment target, and tech stack. **Always read `SPEC.md` first** when starting a session — its "Required sponsors / integrations" and "Deployment" sections are submission-load-bearing.

## Build / run / test / deploy

- **Install:** `<from tech stack — e.g. 'npm install', 'pip install -r requirements.txt'>`
- **Run dev:** `<from tech stack — e.g. 'npm run dev', 'uvicorn main:app --reload'>`
- **Test:** `<from tech stack — or "no tests yet" if the team chose to skip>`
- **Deploy:** `<verbatim from SPEC.md Deployment section — or "TBD" if not yet known>`

## Git policy

- **Never alter git state without explicit approval.** Prohibited without explicit request: `stash`, `reset`, `checkout`, `restore`, `clean`, `commit`, `rebase`, `cherry-pick`, force-push, branch rename / delete, amend. Read-only commands (`log`, `diff`, `blame`, `show`, `status`) are fine.
- **Documented exceptions:** `/kickoff` Phase 4 (initial commit), `/ship-it` Phase 6 (optional commit-after-verify with explicit approval).

## Conventions

- **No drive-by refactors.** Increment scope is what `/ship-it`'s plan said; don't expand silently.
- **Sponsor-required integrations are submission-load-bearing.** If you change one, re-read the relevant `SPEC.md` section before shipping.
- **Hackathon time budget is real.** Prefer the simplest working solution over the cleanest one. Tech debt is okay if it's documented in SPEC.md "Out of scope" or "Open questions".

## Available skills

| Skill | When |
|---|---|
| `/ship-it` | Plan + implement the next increment toward the MVP |
| `/debug` | RCA-first bug-fix loop |
| `/pr-feedback` | Triage + address PR review comments |
| `/skill-create` | Create a new project-local skill |
| `/agent-create` | Create a new project-local subagent |
| `/onboarding` | Re-read the harness walkthrough |
```

**Step 3.3 — `ExitPlanMode`** for the kickoff plan approval. If the dev redirects (different tech stack, different deploy target, different SPEC.md shape), re-enter plan mode with the redirects applied and `ExitPlanMode` again.

### Phase 4 — Execute (per-action gated)

`ExitPlanMode` approved direction. Each write goes through its own gate. Some gates are skipped depending on mode (see "Mode selection" at the top of Workflow).

- **Gate 4.1 — directory create (if needed).** Skipped if the dir already exists (e.g., `--start` mode). `AskUserQuestion`: "Create `<absolute-path>`?" / "Pick a different path" / "Abort." On approve: `mkdir -p <dir>`.

- **Gate 4.2 — file writes.** Skipped if the dir already has all the files (e.g., `--start` mode usually). For `--start` mode, this gate runs only for the `.claude/` install if Phase 1.5 detected it missing. Otherwise: `AskUserQuestion` (single question): "Write the scaffolded files into `<dir>`? (Recommended)" — `preview` shows the file list with sizes. Options: "Yes — write all" / "Yes, but exclude these" (follow-up multiSelect) / "Abort." On approve:
  - Write `SPEC.md` from `templates/SPEC.md` (substitute the `{{...}}` placeholders with interview answers).
  - Write `CLAUDE.md` from `templates/CLAUDE.md` (substitute `{{PROJECT_NAME}}` + tech-stack command placeholders).
  - Write `README.md` (minimal skeleton: project name + 1-line description + "run locally" placeholder).
  - Write `.gitignore` (populated from the chosen tech stack — e.g., `node_modules/`, `__pycache__/`, `.env`, `dist/`).
  - Write `.env.example` (placeholders for sponsor / DB / AI keys mentioned in the interview).
  - Copy the harness's canonical files into the new project's `.claude/`.

  **Resolving the harness root.** This `SKILL.md` lives at `<harness-root>/.claude/skills/kickoff/SKILL.md`. Resolve `<harness-root>` once at the start of Gate 4.2 (three directory levels up from this file's location, or use `$CLAUDE_PROJECT_DIR` if running with that env var set). Reuse the resolved path for all copies in this gate.

  Copy commands:
  ```bash
  HARNESS_ROOT="<resolved-absolute-path>"   # e.g. /Users/<user>/claude-code-hackathon
  DEST="<new-project-dir>"
  mkdir -p "$DEST/.claude"
  cp -R "$HARNESS_ROOT/.claude/agents" "$DEST/.claude/agents"
  cp -R "$HARNESS_ROOT/.claude/skills" "$DEST/.claude/skills"
  cp "$HARNESS_ROOT/templates/settings.example.json" "$DEST/.claude/settings.json"
  ```

  `templates/settings.example.json` becomes the default settings for the new project — the team edits in place. Do NOT copy the harness's own `.claude/settings.json`; it may have harness-developer-specific allowlist entries.

- **Gate 4.3 — `git init` + initial commit.** **Skipped entirely if `--spec-only` mode** (the whole point of `--spec-only` is to defer this). Run for default mode and `--start` mode.

  `AskUserQuestion`: "Run `git init` and create the first commit `chore: kickoff scaffold`?" Options:
  - "Yes — run git init and commit (Recommended)"
  - "Skip git init (we'll do it later via `/kickoff --start`)" — print instructions for the `--start` flow at handoff.
  - "Run git init but skip the commit" — useful if the dev wants to make their own first commit.
  - "Abort."

  On full approve:
  ```bash
  cd <dir>
  git init
  git add SPEC.md CLAUDE.md README.md .gitignore .env.example .claude/
  git commit -m "chore: kickoff scaffold"
  ```

  If the dir is already a git repo (e.g., `--start` mode and the dev ran `git init` themselves between sessions), skip the `git init` and just stage + commit. If the working tree is already clean (nothing to commit), surface that and ask whether to proceed without a commit.

- **Gate 4.4 — remote setup (optional).** **Skipped if `--spec-only` mode** (defer to `--start`). Run for default and `--start`.

  `AskUserQuestion`: "Set up a GitHub remote now?" Options:
  - "Yes — I'll provide the SSH / HTTPS URL" (follow-up free-text) — run `git remote add origin <url>` only; do NOT push (push is the dev's call).
  - "Yes — create a new repo via `gh repo create`" — requires `gh` authenticated; follow up for `org/<name>` or `<name>` (personal). Runs `gh repo create` with `--source=. --private` by default; ask whether private/public before executing.
  - "Skip — I'll set up the remote myself later"
  - "Skip — no remote needed for this project"

### Phase 5 — Handoff summary

The summary changes shape depending on which mode ran:

**Default mode (interview + scaffold + git init):**

```
Kickoff complete. Project scaffolded at <dir>.

What's in there:
  SPEC.md         — canonical project context (every downstream skill reads this)
  CLAUDE.md       — project-root rules + commands
  README.md       — minimal skeleton (expand as you build)
  .gitignore      — pre-populated for <tech stack>
  .env.example    — placeholders for <sponsor / DB / AI keys>
  .claude/        — hackathon harness (agents, skills, settings)

Git state:
  - Initialized? <yes / no>
  - First commit? <yes / no — sha if yes>
  - Remote? <"origin <url>" / "none">

Open questions in SPEC.md (will be re-surfaced on first /ship-it):
  - <list, or None.>

Next step:
  cd <dir>
  claude            # start a Claude Code session in the project dir
  /ship-it          # plan + implement the first increment toward MVP
```

**`--spec-only` mode (interview + scaffold, no git):**

```
Spec prep complete. Project planned at <dir>.

What's in there:
  SPEC.md         — your team's commitments (sponsors, deploy, tech stack, MVP criteria)
  CLAUDE.md       — project-root rules + commands
  README.md       — minimal skeleton
  .gitignore      — pre-populated for <tech stack>
  .env.example    — placeholders for <sponsor / DB / AI keys>
  .claude/        — hackathon harness (agents, skills, settings) — ready to use

Git state:
  - Initialized? NO — deferred until hackathon start
  - The harness is installed and ready; no commits yet.

Open questions in SPEC.md (resolve before hackathon start, or carry forward to first /ship-it):
  - <list, or None.>

What to do now:
  - Review / edit SPEC.md to refine your plan ahead of the hackathon.
  - Share <dir>/SPEC.md with your teammates for review.

When the hackathon starts:
  cd <dir>
  claude
  /kickoff --start          # reads existing SPEC.md, confirms, runs git init + first commit
  # then start building
  /ship-it
```

**`--start` mode (git init only, spec was already written):**

```
Hackathon started. Git initialized at <dir>.

Git state:
  - Initialized? yes
  - First commit? <sha> ("chore: kickoff scaffold")
  - Remote? <"origin <url>" / "none">

SPEC.md is canonical — refer back to it whenever scope feels uncertain.
Open questions still in SPEC.md (will be re-surfaced on first /ship-it):
  - <list, or None.>

Next step:
  /ship-it          # plan + implement the first increment toward MVP
```

If `--dry-run` was set: skip Phases 4 and 5; instead print "Dry-run — files would be written to `<tmp-dir>`; diff is at `<tmp-dir>`" and exit.

## What this skill does not do

- **Does not write code beyond the scaffold files.** The first feature increment is `/ship-it`'s job.
- **Does not push to a remote.** Even when Gate 4.4 sets up `origin`, the dev runs `git push -u origin main` themselves.
- **Does not install dependencies (`npm install` / `pip install`).** That's the dev's first command after `cd <dir>` — kickoff stays out of the dev's build cycle.
- **Does not run the dev server.** Same reason — the dev's machine, the dev's call.
- **Does not assume any tech-stack default.** Every choice is asked. If you have an opinion about what hackathon teams *should* use, that opinion does not belong in this skill.
- **Does not commit secrets.** `.env.example` is the only `.env`-flavored file written; the real `.env` is gitignored.

## Troubleshooting

- **`<dir>` is non-empty** — Non-negotiable #2 handles this. If the dev chooses "adopt into existing project", skip Gate 4.1 (dir already exists) and only write the files the project doesn't already have — confirm per-file before any overwrite. If the dir is already a git repo, skip `git init`.
- **The dev ran `/kickoff` from inside `claude-code-hackathon/` and picked "Use current cwd"** — surface the warning at Phase 1 Step 2 explicitly: "Cwd is the harness directory. Writing the project here will mix harness files with your project files. Recommend picking 'sibling of this dir' or a custom path instead."
- **`--start` invoked but no SPEC.md exists** — Phase 1.5 Step 1 aborts with a pointer at `--spec-only`. Print the suggested invocation; don't retry.
- **`--start` invoked but the dev wants to edit SPEC.md significantly first** — Phase 1.5 Step 3 has the "needs significant rework → go back to interview" path. Treat as a fresh interview but pre-fill questions from the existing SPEC.md content.
- **`--spec-only` finished but the dev now wants git init in the same session** — they can re-invoke `/kickoff --start <dir>` immediately. The skill picks up the existing SPEC.md from Phase 1.5 and runs only Gates 4.3 + 4.4.
- **Tech-stack choice doesn't match a preset option** — pick "Other — I'll describe" and let the dev free-text. Capture verbatim into SPEC.md; the implementor will adapt.
- **Sponsor list is long (>4)** — multiSelect first, then per-sponsor follow-ups batched ≤4 per `AskUserQuestion` call (multiple sequential calls if needed).
- **`gh` not authenticated for Gate 4.4** — print the `gh auth login` command, fall back to "skip — I'll set up the remote myself."
- **The dev says "you assumed X"** — re-surface X as a new `AskUserQuestion` round. Revisit SPEC.md if the assumption already landed in the file (Phase 4 has not run yet most of the time, but if it has, edit the file in place and re-commit).
