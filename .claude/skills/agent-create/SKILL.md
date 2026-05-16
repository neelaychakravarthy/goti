---
name: agent-create
description: Guided creation of a new project-local subagent for the current hackathon project. Interviews the dev for the agent's role, model tier, tool allowlist, context inputs, and read-only-vs-writes shape; scaffolds a contract conforming to existing agent conventions (Role / Input / Procedure / Output format / Constraints) directly into `.claude/agents/<name>.md`. Sister to `/skill-create`. Plan-gated before any file write.
trigger: /agent-create
---

# /agent-create

Sister skill to `/skill-create` for creating project-local subagents. Hand-authoring agent files requires remembering frontmatter shape (`name` / `description` / `tools` / `model`), standard body sections (Role / Input / Procedure / Output format / Constraints), and universal constraints (read-only by default, no nested `Agent` dispatch, cite by symbol not line numbers, never fabricate). `/agent-create` orchestrates: **interview → scaffold → iterate**.

The draft lands in `.claude/agents/<name>.md` of the current project — no source-of-truth/install split. The dev then **restarts the Claude Code session** so the new agent is discoverable (agents load at session start; they do not hot-reload — different from skills).

This skill only creates **agents**. Creating slash-command skills is `/skill-create`'s job. If the dev is trying to create a skill, flag the mismatch and stop.

## Usage

```
/agent-create <name>                                       # interview → scaffold
/agent-create <name> --read-only                           # skip the read-only-vs-writes question
/agent-create <name> --writes-files                        # skip the read-only-vs-writes question
/agent-create --continue <name>                            # resume iteration
/agent-create --update <name>                              # re-edit an existing agent
```

**Name rules.** Kebab-case. Must match the agent's frontmatter `name:` ↔ file path `.claude/agents/<name>.md`. No leading slash (agents aren't slash-commands; the name is what the parent skill passes to `Agent(subagent_type: "<name>")`).

## Non-negotiables

1. **Never overwrite an existing agent file without confirmation.** If `.claude/agents/<name>.md` already exists, fire `AskUserQuestion`: "Overwrite" / "Treat as `--update`" / "Pick a different name" / "Abort." Never silently clobber.
2. **Plan-gated before any file write.** `EnterPlanMode` + `ExitPlanMode` covers the scaffold direction.
3. **Testing happens in the dev's hands — and a session restart is required.** Never dispatch `Agent(subagent_type: "<new-agent>")` against the in-progress file — recursive + the agent isn't loaded. After file write, the dev restarts the Claude Code session. **Skills hot-load; agents do not.**
4. **Interactive prompts use `AskUserQuestion`; the plan uses `EnterPlanMode` + `ExitPlanMode`.** Never dump a long markdown document asking for a bulk inline reply. Batch ≤4 questions per `AskUserQuestion` call.
5. **Zero assumptions on interview answers.** Every design choice with ≥2 viable options surfaces as `AskUserQuestion` before the scaffold is written.
6. **Scope stays on the one agent.** One agent per invocation. No parallel edits.
7. **No git mutations.** Lay down the file; the dev commits.

## Workflow

### Phase 1 — Intent interview

**Step 1 — parse the invocation.** Extract `<name>`, `--read-only` / `--writes-files`, `--continue`, `--update`.

- `/agent-create --continue <name>` → re-read `.claude/agents/<name>.md`, skip to Phase 3.
- `/agent-create --update <name>` → re-edit; skip collision check.
- Otherwise continue to Step 2.

**Step 2 — collision check.** Does `.claude/agents/<name>.md` exist? If yes → Non-negotiable #1.

**Step 3 — confirm agent-vs-skill.** If the dev's request mentions "slash command", "/<name>" trigger, or implies an interactive workflow, fire `AskUserQuestion`: "This skill creates **subagents** (Agent-tool callees with a fixed input contract and output format), not slash-command skills. Options: Proceed (subagent) / Abort (use `/skill-create`)."

**Step 4 — interview (three rounds of `AskUserQuestion`, ≤4 questions each):**

*Round 1 — shape:*

1. **One-line description** (frontmatter `description:`) — options: "I'll draft based on purpose, you word-smith" / "You dictate, I'll use verbatim" / "Free text now". Load-bearing — parent skills read this to decide when to dispatch. Specific, action-oriented (25–60 words).
2. **Read-only vs write-capable** (if not set by flag). Single-select with previews:
   - **Read-only** (Recommended for most new agents) — tools = `Read, Glob, Grep, Bash`. Body has Role / Input / Procedure / Output format / Constraints. No "Hard invariants" section. Constraints: "Read-only. No Edit/Write. No git mutations."
   - **Write-capable** — tools include `Edit, Write, NotebookEdit`. Body adds **Hard invariants** before Input (mirrors `implementor`): "Stay within scope" / "Leave the project deployable" / "No git state changes" / "Ask back instead of assuming." Constraints add "No new dependencies without approval" / "Honest verification."
3. **Model tier** — single-select:
   - **`sonnet`** (Recommended for structured-output / classification work) — used by `context-gatherer`. Cheap, fast, good at filling structured templates.
   - **`opus`** — used by `investigator` / `implementor`. Deep reasoning, cross-cutting investigation, decisions-with-confidence.
   - **`haiku`** — rarely the right choice; only when the work is purely mechanical and latency-sensitive.
4. **Tools allowlist** — multiSelect over the standard menu:
   - `Read, Glob, Grep, Bash` (Recommended baseline)
   - `Edit, Write, NotebookEdit` (auto-selected if Round-1 Q2 = write-capable)
   - any `mcp__<server>__<tool>` the project's settings expose (if the hackathon team has wired up MCP servers — this is rare)

*Round 2 — context inputs (what the new agent consumes):*

5. **Reads SPEC.md?** — yes (Recommended) / no. If yes, the agent's Input section pre-fills "Read `<project-root>/SPEC.md` for the canonical project context."
6. **Reads recent git history?** — yes / no. If yes, Procedure pre-fills the `git log --oneline -20` / `git status --short` idioms.
7. **Skills consumed** — multiSelect (rare). If non-empty, frontmatter gets a `skills: [...]` line and Procedure references the consumed skill.

*Round 3 — purpose:*

8. **One-line role statement.** The opening of `# Role`. Answer "what one question / one task does this agent answer / perform?" in a single sentence.
9. **Input contract draft.** What the parent passes. Free-text bulleted list, mapped to Input section. Required vs optional explicit.
10. **Output format draft.** What the parent gets back. Free-text — scaffold renders this as a single fenced markdown block with fixed headings. Empty sections keep the heading and write `None.`.

**Step 5 — announce captured interview.** Restate as a short bullet list in chat — no `ExitPlanMode` here.

### Phase 2 — Plan + scaffold

**Step 1 — `EnterPlanMode`** → present the plan. Plan contents:

1. **Target file:** `.claude/agents/<name>.md`.
2. **File writes** (after gate 2.1):
   - `.claude/agents/<name>.md` — scaffolded per variant, filled from interview.
3. **Preview ~30 lines of the scaffold** so the dev sees the skeleton before approval.
4. **Dev's next step:** **Restart the Claude Code session** so the agent is discoverable. Then dispatch the agent from a parent skill (or a one-off `Agent` call mimicking the parent's input contract).

Call `ExitPlanMode`.

**Step 2 — file-write gate.** `AskUserQuestion`: "Write `.claude/agents/<name>.md`? (Recommended)" / "Change path / Abort."

On approve: write the file.

**Step 3 — announce + dev next step.**

Tell the dev:
- Absolute path written.
- One-line summary (variant, model, tools, context inputs).
- Next step:
  > **Restart the Claude Code session** so the new agent is discoverable. Agents load at session start; they don't hot-reload. After restart, dispatch the agent from a parent skill or via a one-off `Agent` call to test. Report what's off or say "done" when ready.
- Do NOT auto-invoke (Non-negotiable #3).

## Agent skeletons

**Common to both variants** — frontmatter:

```yaml
---
name: <name>
description: <from Round-1 Q1>
tools: <comma-separated allowlist from Round-1 Q4>
model: <sonnet | opus | haiku, from Round-1 Q3>
skills: [<list, from Round-2 Q7; omit field if empty>]
---
```

**Variant — read-only** (default; mirrors `context-gatherer` / `investigator`):

```markdown
# Role

You are <one-line role from Round-3 Q8>. The parent workflow has hit a point where it needs <what this agent uniquely provides>. Your job is to <one-sentence task>.

You do not implement, do not edit, do not <other things this agent does NOT do>. You <verbs that match — investigate / gather / classify / etc>.

# Input

The invoking skill will provide:
- **<input field 1>** (required) — <description from Round-3 Q9>
- **<input field 2>** (optional) — <description>
- ...

<!-- TODO(agent-create): fill in remaining input contract from Round-3 Q9. -->

# Procedure

<!-- TODO(agent-create): fill in numbered steps. -->

## 1. <first step — usually "restate the question" or "orient in the input">

<details>

## 2. <next step>

<details>

<!-- If Round-2 Q5 = SPEC.md-yes, insert step: -->
## N. Read SPEC.md

Read `<project-root>/SPEC.md` for the canonical project context. Re-read the relevant section verbatim for your work — sponsor requirements, deployment target, MVP acceptance criteria are load-bearing.

# Output format

Respond with a single block in exactly this shape. Keep every heading even if the section is empty (write `None.`).

\`\`\`markdown
# <output title — one line summarizing the work>

## <section 1 from Round-3 Q10>
- <bullet shape, or 1-3 sentence prose>

## <section 2>
- ...

## Open questions for the human
- <anything only the dev can answer>
\`\`\`

# Constraints

- **Read-only.** No Edit/Write/NotebookEdit. No git mutations. Bash is for read-only commands (`git log`, `git diff`, file reads, `grep`) only.
- **Cite by symbol, not line number.** Line numbers drift.
- **Never fabricate.** If a file doesn't contain what you expected, say so. Do not invent.
- **Stay scoped.** Do not investigate adjacent-but-unasked questions. Flag them under "Open questions for the human".
- **No nested agent dispatch.** Do not call `Agent` yourself.
```

**Variant — write-capable** (mirrors `implementor`):

```markdown
# Role

You implement <scoped work — from Round-3 Q8> in the hackathon project. A parent skill has already planned the work and received the developer's approval. Your job is to execute the plan accurately and within scope.

You do **not** expand scope, invent requirements, or decide what to build. If the plan is unclear, report that and stop — do not guess.

# Hard invariants

1. **Stay within scope.** The parent will give you a scope boundary. If the work requires editing outside that boundary, **stop and report** — do not silently expand.
2. **Leave the project deployable.** Every increment must end with the project still working. If your change requires temporarily breaking deploy, stop and report.
3. **No git state changes.** No `commit`, `checkout`, `reset`, `rebase`, `stash`, `cherry-pick`, `clean`, `push`, `pull`, or branch operations. Read-only git (`log`, `diff`, `blame`, `show`, `status`) fine.
4. **Ask back instead of assuming.** If you hit a decision the plan doesn't cover, report it in "Open questions" and skip that piece.

# Input

<!-- same shape as read-only variant — Round-3 Q9 contents -->

# Procedure

<!-- TODO(agent-create): standard implementor shape — orient → implement → verify → self-critique. -->

# Output format

<!-- single block matching implementor's structure: Summary / Files changed / Verification / Deployable-state check / Scope compliance / Acceptance criteria check / Open questions / Follow-ups -->

# Constraints

- **No git mutations.** Read-only git only.
- **No scope expansion.** Touch only what the scope boundary allows.
- **No new dependencies** without approval.
- **Honest verification.** If you didn't run a test, say so. Never silently weaken a test to make it pass.
- **Never fabricate.**
- **No nested agent dispatch.**
```

**Dev-editable sections** are marked `<!-- TODO(agent-create): ... -->`. Do not leave TODOs in frontmatter, the Role one-liner, or Constraints.

### Phase 3 — Iteration loop

Triggered when the dev returns with feedback (or immediately after Phase 2 if `--continue` was used).

**Step 1 — re-read** `.claude/agents/<name>.md`. Treat the on-disk file as authoritative.

**Step 2 — categorize each piece of feedback.**
- *Small hot-fixes* (typos, rewording): edit directly, no gate.
- *Design-affecting changes* (model tier, read-only-vs-writes, tool allowlist, Procedure step): if ≥2 plausible resolutions, surface via `AskUserQuestion` before editing.

**Step 3 — edit.** Use `Edit` on the agent file. Report what changed in one or two sentences.

**Step 4 — prompt for next iteration or done.**
> **Restart the Claude Code session** to pick up agent changes (agents don't hot-reload). Then dispatch the agent to test. Report what's still off, or say "done" / "ship it" when ready.

Loop on Step 1 when the dev returns.

### Phase 4 — Optional commit

Same shape as `/skill-create` Phase 4. Dev says "done"; `AskUserQuestion` for commit message, `git add .claude/agents/<name>.md && git commit`. Never push.

## Re-editing an existing agent (`--update`)

Differences from create:
- **No collision check.**
- **Phase 2 plan** includes a diff preview: `git diff -- .claude/agents/<name>.md`.
- **Phase 4 commit message** uses `Update` instead of `Add`.

## What this skill does not do

- **Does not create slash-command skills.** That's `/skill-create`'s job.
- **Does not restart the Claude Code session for you.** Manual dev action — needed after every agent file change.
- **Does not invoke the draft agent mid-iteration.** Dev-driven testing only (Non-negotiable #3).
- **Does not push.** Dev's call.
- **Does not edit other agents "while it's here."** One agent per invocation (Non-negotiable #6).
