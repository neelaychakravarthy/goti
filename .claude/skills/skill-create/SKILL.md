---
name: skill-create
description: Guided creation of a new project-local Claude Code skill for the current hackathon project. Interviews the dev for shape + purpose, scaffolds a tiered SKILL.md directly into the project's `.claude/skills/<name>/` directory. Plan-gated before any file write. Designed for hackathon time pressure — no source-of-truth/install separation; the file lands where the harness reads it.
trigger: /skill-create
---

# /skill-create

Orchestrates creation of a new project-local Claude Code skill: **interview → scaffold → iterate**. The draft lands in `.claude/skills/<name>/SKILL.md` of the current project — no separate source-of-truth repo, no install step. Skills hot-load: edited skills take effect on the next `/<name>` invocation.

This skill only creates **skills**. Creating subagents under `.claude/agents/` is `/agent-create`'s job. If the dev is trying to create an agent, flag the mismatch and stop.

## Usage

```
/skill-create <name>                                   # interview → scaffold
/skill-create <name> --tier simple|phased|plan-gated   # skip the tier question
/skill-create --continue <name>                        # resume iteration
/skill-create --update <name>                          # re-edit an existing skill
```

**Name rules.** Kebab-case. Must match the slash trigger (`/<name>` ↔ `.claude/skills/<name>/SKILL.md`). No leading slash in the argument.

## Non-negotiables

1. **Never overwrite an existing SKILL.md without confirmation.** On scaffold, if `.claude/skills/<name>/SKILL.md` already exists, fire `AskUserQuestion`: "Overwrite" / "Treat as `--update`" / "Pick a different name" / "Abort". Never silently clobber.
2. **Plan-gated before any file write.** `EnterPlanMode` + `ExitPlanMode` covers the scaffold direction. Files lay down only after `ExitPlanMode` approves.
3. **Interactive prompts use `AskUserQuestion`; the plan uses `EnterPlanMode` + `ExitPlanMode`.** Never dump a long markdown document asking for a bulk inline reply. Batch ≤4 questions per `AskUserQuestion` call.
4. **Zero assumptions on interview answers.** Every design choice with ≥2 viable options surfaces as `AskUserQuestion` before the scaffold is written. Defaults proposed in the plan must still be confirmed.
5. **Testing happens in the dev's hands, not Claude's.** Never invoke the Skill tool against the in-progress SKILL.md from inside this skill — recursive invocation. Dev invokes `/<name>` and reports what's off.
6. **Scope stays on the one skill.** Don't suggest parallel edits ("while we're at it, let's also update X"). One skill at a time.
7. **No git mutations.** This skill lays down files; the dev commits when ready. Don't auto-commit, don't auto-push.

## Workflow

### Phase 1 — Intent interview

**Step 1 — parse the invocation.** Extract `<name>`, `--tier`, `--continue`, `--update`.

- `/skill-create --continue <name>` → re-read `.claude/skills/<name>/SKILL.md`, skip to Phase 3.
- `/skill-create --update <name>` → re-edit existing skill on the current project; same flow as create but skips collision check.
- Otherwise continue to Step 2.

**Step 2 — collision check.** Does `.claude/skills/<name>/SKILL.md` exist? If yes → Non-negotiable #1. If no → proceed.

**Step 3 — confirm agent-vs-skill.** If the dev's request mentions "agent", "subagent", "tool allowlist", or implies an `Agent`-tool callee, fire a single `AskUserQuestion`: "This skill creates slash-command skills only, not subagents — those are `/agent-create`'s job. Options: Proceed (I'm building a slash-command skill) / Abort (I actually want `/agent-create`)."

**Step 4 — interview (three rounds of `AskUserQuestion`, ≤4 questions each):**

*Round 1 — shape:*

1. **One-line description** (frontmatter `description:`) — options: "I'll draft based on purpose, you word-smith" / "You dictate, I'll use verbatim" / "Free text now". The description is load-bearing — Claude Code uses it to decide when the skill is relevant. Write specific, action-oriented sentences (25–60 words).
2. **Tier** (if not set by `--tier`). Single-select with previews:
   - **simple** — Usage + flat Workflow. 1-page contract, minimal guardrails. Example fit: one-shot utility skills.
   - **phased** (Recommended for most new skills) — Usage + ≤3 non-negotiables + numbered phases (no plan-mode gate). Example fit: workflow skills like `/debug`.
   - **plan-gated** — Usage with flags + numbered non-negotiables (plan-mode + zero-assumptions + no-git-without-approval) + numbered phases ending in Finalize. Example fit: `/ship-it`, `/kickoff`.
   Use `preview` on each option with a 10–15-line skeleton.
3. **Git-state touching** — "none" / "read-only (`log`, `diff`, `status`)" / "writes (commit / branch / push)". If **writes**, the scaffold pre-fills the "Never alter git state without explicit approval" non-negotiable.
4. **Code-editing** — "yes, dispatches `implementor`" / "no, read-only" / "conditional (read-only until plan approves, then dispatches implementor)".

*Round 2 — context inputs:*

5. **Reads `SPEC.md`?** — yes (Recommended) / no. If yes, the scaffold pre-fills a "Read SPEC.md first" step in Phase 1.
6. **Sub-agents dispatched** — multiSelect over `context-gatherer` / `investigator` / `implementor` / none. The scaffold pre-fills the `Agent` call shape for each selected agent.
7. **Publishes output** — multiSelect over "none" / "GitHub PR / review / reply (via `gh`)" / "writes file to repo" / "git commit". Each selected option pre-fills a dedicated approval gate in the Finalize phase.

*Round 3 — purpose:*

8. **Problem statement (free text, 1–3 sentences).** What does this skill do that doesn't already exist? What's the current pain? Lands directly in the scaffold's opening paragraph.

**Step 5 — announce captured interview.** Restate as a short bullet list in chat — no `ExitPlanMode` here. Give the dev one chance to correct before Phase 2.

### Phase 2 — Plan + scaffold

**Step 1 — `EnterPlanMode`** → present the plan. Plan contents:

1. **Target file path:** `.claude/skills/<name>/SKILL.md` (under the current project root).
2. **File writes** (after gate 2.1):
   - `.claude/skills/<name>/SKILL.md` — scaffolded per tier-skeleton, filled from interview.
3. **Preview ~30 lines of the chosen tier's scaffold** so the dev sees the skeleton before approval. Don't dump all 200+ lines.
4. **Dev's next step:** invoke `/<name>` to test. Skills hot-load — no restart needed for skills (agents are different; they need a restart).

Call `ExitPlanMode`.

**Step 2 — `AskUserQuestion` for the file-write gate.**

`ExitPlanMode` approves direction; the file-write gate is separate.

- **Gate 2.1 — write the skill file.** `AskUserQuestion`: "Write `.claude/skills/<name>/SKILL.md`? (Recommended)" / "Change the path / Abort." Show the full path being written.
- On approve: write the file. Use the tier skeleton + interview pre-fills.

**Step 3 — announce + dev next step.**

Tell the dev:
- Absolute path written.
- One-line summary of what's in the scaffold (tier, dispatched agents, non-negotiables).
- Next step:
  > Invoke `/<name>` to test the scaffold. Skills hot-load — no restart needed. Report what's off (missing phase, wrong tone, too many / too few questions) or say "done" when ready.
- Do NOT auto-invoke `/<name>` (Non-negotiable #5).

## Tier skeletons

**Common to all tiers** — frontmatter:

```yaml
---
name: <name>
description: <from Round-1 Q1>
trigger: /<name>
---
```

The `description` field is load-bearing: Claude Code uses it to decide when the skill is relevant. Write specific, action-oriented (25–60 words).

**Tier — simple:**
```markdown
# /<name>

<one-paragraph purpose, from Round-3 Q8>

## Usage

\`\`\`
/<name>                     # <describe default behavior>
/<name> <arg>               # <describe arg-ed form>
\`\`\`

## Workflow

1. <step 1 — flat, no phases>
2. <step 2>
3. <step 3>

<!-- TODO(skill-create): flesh out each step with concrete commands / tool calls / decision points. -->
```

**Tier — phased:**
```markdown
# /<name>

<one-paragraph purpose>

## Usage

\`\`\`
/<name> <forms>
\`\`\`

## Non-negotiables

1. **<constraint 1>** — <one-line rationale>
2. **<constraint 2>** — <one-line rationale>
3. **<constraint 3>** — <one-line rationale>

## Workflow

### Phase 1 — <name>

<!-- TODO(skill-create): ... -->

### Phase 2 — <name>

<!-- TODO(skill-create): ... -->

### Phase 3 — <name>

<!-- TODO(skill-create): ... -->
```

**Tier — plan-gated:**
```markdown
# /<name>

<one-paragraph purpose>

## Usage

\`\`\`
/<name> <forms, including --dry-run and --continue where applicable>
\`\`\`

## Non-negotiables

1. **Never alter git state without explicit approval.** <context>
2. **Plan-gated before any write.** `EnterPlanMode` + `ExitPlanMode` before Phase N; per-action `AskUserQuestion` gates inside Phase N.
3. **Zero assumptions on design choices.** Every ≥2-option decision goes through `AskUserQuestion` before the plan is finalized.
4. **Interactive approvals use built-in tools.** `AskUserQuestion` / `EnterPlanMode` / `ExitPlanMode` — not inline markdown dumps.
5. **<skill-specific constraint>** — <rationale>

## Workflow

### Phase 1 — Context gathering (read-only)
<!-- TODO(skill-create): read SPEC.md if applicable, dispatch context-gatherer for relevant work. -->

### Phase 2 — Plan + approval gate
<!-- TODO(skill-create): EnterPlanMode → ExitPlanMode. AskUserQuestion for design choices. -->

### Phase 3 — Execute
<!-- TODO(skill-create): the actual work. For any git write / external publish, separate AskUserQuestion gate. -->

### Phase 4 — Finalize
<!-- TODO(skill-create): commit drafting, cleanup, dev-facing summary. No push without explicit approval. -->
```

**Pre-fill from the interview:**
- If Round-2 Q5 = SPEC.md-yes → Phase-1 stub includes "Read `SPEC.md` first."
- If Round-2 Q6 includes **context-gatherer** → Phase-1 stub references the dispatch shape.
- If Round-2 Q6 includes **implementor** → plan-gated Phase 3 stub shows the dispatch pattern.
- If Round-2 Q7 includes **git commit/push** or **GitHub PR** → add the respective approval gate in Finalize.

**Dev-editable sections** are marked `<!-- TODO(skill-create): ... -->` so the dev can grep for unfinished parts. Do not leave TODOs in the frontmatter, the Usage block, or the Non-negotiables list — those are determined by the interview.

### Phase 3 — Iteration loop

Triggered when the dev returns with feedback after testing (or immediately after Phase 2 if `--continue` was used).

**Step 1 — re-read** `.claude/skills/<name>/SKILL.md`. Treat the on-disk file as authoritative.

**Step 2 — categorize each piece of feedback.**
- *Small hot-fixes* (typos, rewording, formatting): edit directly, no gate.
- *Design-affecting changes* (add/remove a phase, add/remove a non-negotiable, change the dispatched agent, change the tier): if ≥2 plausible resolutions, surface via `AskUserQuestion` before editing. If exactly one right answer is specified, edit.

**Step 3 — edit.** Use `Edit` on the SKILL.md. Report what changed in one or two sentences (not a diff dump).

**Step 4 — prompt for next iteration or done.**
> Invoke `/<name>` again to test. Report what's still off, or say "done" / "ship it" when it's ready to commit.

Loop on Step 1 when the dev returns.

### Phase 4 — Optional commit

Triggered by the dev saying "done" / "commit" / "ship it" in Phase 3.

**Step 1 — `AskUserQuestion`:**
- "Stage and commit `.claude/skills/<name>/SKILL.md` — I'll draft the message" (Recommended) — Claude reviews the file, drafts a message (e.g., `Add /<name> skill — <one-line purpose>`), dev approves / edits, then `git add .claude/skills/<name>/SKILL.md && git commit -m "<approved>"`.
- "Commit — I have a message in mind" — dev supplies, Claude runs `add` + `commit`.
- "Skip — I'll commit later or as part of a larger commit."

**Step 2 — print push suggestion (do not execute):**
> When ready: `git push`. (First push on a new branch: `git push -u origin <branch>`.)

## Re-editing an existing skill (`--update`)

Differences from create:
- **No collision check** — the skill existing is the precondition for `--update`.
- **Phase 2 plan** includes a diff preview: `git diff -- .claude/skills/<name>/SKILL.md` to show what's about to change.
- **Phase 4 commit message** uses `Update` instead of `Add`.

## What this skill does not do

- **Does not create agents** under `.claude/agents/`. That's `/agent-create`'s job.
- **Does not run the new skill mid-iteration.** Dev-driven testing only (Non-negotiable #5).
- **Does not push.** Even when Phase 4 commits, push is the dev's call.
- **Does not edit other skills "while it's here."** One skill per invocation (Non-negotiable #6).
