---
name: ship-it
description: Plan + implement the next increment toward the hackathon MVP, anchored on SPEC.md. Reads spec context (project, sponsors, deployment, tech stack), proposes a small step that leaves the project deployable, iterates with the team on design choices, and dispatches the implementor agent inside a plan-mode approval gate. Designed for rapid, small, robust increments — never lands code without an approved plan, never expands beyond the agreed scope.
trigger: /ship-it
---

# /ship-it

The core development loop. Each invocation = one increment. An increment is small enough to ship in 30–90 minutes of real time, ends with the project still deployable, and moves measurably toward the MVP defined in `SPEC.md`.

`/ship-it` is opinionated on **shape** (plan → ask → implement → verify → wrap), not on **scope**. The team owns scope through `AskUserQuestion` answers; the skill enforces that the increment is genuinely incremental and that no code lands without explicit approval.

## Usage

```
/ship-it                                # asks what to build next; picks an increment with the team
/ship-it "<free-text>"                  # team has a specific increment in mind; describe it
/ship-it --re-scope                     # currently-planned increment is too big — re-decompose
/ship-it --continue                     # resume after a paused approval gate
/ship-it --dry-run                      # full plan, no file writes
```

## Non-negotiables

1. **Never edit code before the user approves the plan.** Phase 1 → Phase 2 (iterate via `AskUserQuestion`) → `ExitPlanMode` → Phase 3 (implementor) is the only path. No silent edits.
2. **Zero assumptions on design choices.** Any decision with ≥2 viable options (tech approach, sponsor SDK choice, file layout, data shape, scope boundary, library, fixture pattern) surfaces as `AskUserQuestion` before the plan is finalized. Proposing X in the plan and relying on the dev to redirect at `ExitPlanMode` is forbidden. Only mechanical defaults with no viable alternative may go in the plan as "mechanical assumptions" — each with a one-line justification.
3. **Each increment leaves the project deployable.** The plan must end with the project in a state the team can demo / show / serve. If an increment naturally requires breaking the deploy path (e.g., migrating a DB schema), the plan must include a same-increment rollforward — never ship a half-broken state.
4. **Never alter git state without explicit approval.** No `commit`, `branch`, `checkout`, `reset`, `stash`, `rebase`, `push`. Phase 6's optional commit is gated.
5. **Hackathon time is real.** When a question has a "simplest path that works" option, that option is recommended unless the team has explicitly chosen quality over speed in SPEC.md. The framing: "ship the demo, document the debt."
6. **Sponsor-required integrations are submission-load-bearing.** Whenever an increment touches a sponsor-required area (per `SPEC.md`'s "Required sponsors / integrations"), the plan must explicitly call out the sponsor and the integration depth the implementor must hit. The implementor's report will verify this.
7. **Self-critique on missed assumptions.** If the dev says "you assumed X" or "you didn't ask about Y", acknowledge, re-surface X as a new `AskUserQuestion` round (not just a chat acknowledgment), and check whether the already-written plan needs updating. Do not mention this rule unless triggered.
8. **Interactive approvals use built-in tools.** `AskUserQuestion` (batch ≤4 per call) for choices, `EnterPlanMode` / `ExitPlanMode` for the plan. Never dump a plan in chat and ask for bulk approval.

## Workflow

### Phase 1 — Context gathering (read-only)

**Step 1 — invocation parsing.** Extract any free-text increment description, flags. If `--continue`, re-read the in-progress plan from `~/.claude/plans/` (if any) and skip to where the previous run paused.

**Step 1a — SPEC.md existence check.** If `SPEC.md` doesn't exist in the project root, fire `AskUserQuestion`:
- "Run `/kickoff` first to scaffold SPEC.md (Recommended)" — print the suggested invocation and exit cleanly.
- "Proceed without SPEC.md — I'll describe the project inline" (follow-up free-text) — `/ship-it` continues but every downstream agent will be told "no SPEC.md; project context is inline."
- "Abort."

**Step 2 — Dispatch `context-gatherer`** with:
- **Purpose:** `"/ship-it: planning the next increment — <free-text from invocation, or 'team will pick'>"`
- **Focus symbols / files:** anything the user mentioned in the invocation (paths, symbol names).
- **Working directory:** project root.

The agent returns a structured brief — SPEC.md highlights, CLAUDE.md rules, recent commits, focus findings, open context gaps. Feed this brief into Phase 2 verbatim.

**Fallback to inline** only if `Agent(subagent_type: "context-gatherer")` returns "not found" (agents haven't loaded in this session). Tell the user the session needs a restart, then run the equivalent reads inline (read `SPEC.md`, `CLAUDE.md`, `git log --oneline -10`, `git status --short`).

### Phase 2 — Pick + shape the increment (iterative, plan-mode approval gate)

The flow: first-round questions → `EnterPlanMode` + targeted research → pre-finalize question batch → write plan file (resolved decisions only) → publish plan (optional) → `ExitPlanMode`.

**Step 2.1 — First-round questions (before plan mode).**

Resolve top-level choices the brief surfaced. Typical first-round questions, fired as a single `AskUserQuestion` batch (≤4):

a. **Which increment?** Options assembled from SPEC.md "MVP acceptance criteria" + open questions + the free-text description. Each option should be a concrete, named increment ("Add login flow via Sponsor X SDK" / "Wire up DB schema for users + sessions" / "Build the demo landing page"). Include "Different — I'll describe" as a fallback. Use `preview` to show the rough scope-shape per option.

b. **What 'done' looks like for this increment** — options should be 2–3 concrete acceptance-criterion sketches the implementor will hit. "Recommended" only when one is clearly load-bearing for the MVP.

c. **Time budget** — options: "30 min (smallest viable slice)" / "60 min (typical)" / "90 min (bigger — split if it grows)" / "Don't time-box — implementor runs to completion". Affects how aggressively the implementor self-trims when scope expands mid-implementation.

d. **Touches a sponsor-required integration?** Pulled from SPEC.md's sponsor list. Options: per-sponsor multiSelect with "None — this increment doesn't touch sponsors" as an option. When a sponsor is selected, the implementor must verify the integration depth recorded in SPEC.md is hit.

If the dev picks "Different — I'll describe" or otherwise overrides the proposed increment shape, capture the free-text answer and fire **one follow-up `AskUserQuestion`** to confirm the acceptance criteria for the new shape before moving on.

**Step 2.2 — `EnterPlanMode`; targeted research.**

Inside plan mode, do targeted reads:
- Files the increment will touch (or create).
- Relevant SPEC.md sections re-read in full (sponsor block, deployment block, tech stack block, MVP acceptance criteria).
- The deploy command (from SPEC.md or CLAUDE.md) — confirm it's still valid; if the team has migrated since, flag it.

Dispatch `Explore` subagents in parallel only if the increment crosses unfamiliar code (e.g., touching a sponsor SDK you haven't read yet). Cap at 2 parallel explores — hackathon time budget makes broad exploration expensive. Each explore should be a single focused question, not "tell me everything about X."

When dispatching, explicitly require:
- Every design choice with ≥2 viable options returned as an explicit option block ("Option A: use Sponsor X's `/v2/auth` endpoint / Option B: use their hosted-UI redirect").
- Every tentative value (config keys, env var names, library names) flagged as "tentative — alternatives are ...".
- Load-bearing claims verified by reading the code, not inferred.

**Step 2.3 — Pre-finalize question batch.**

After research returns, collect every design choice and every tentative value. Fire **`AskUserQuestion`** rounds — batched ≤4 per call, multiple sequential calls if more. Each question must include:

- **Full context** — what the choice is, why it matters, what code/data is affected.
- **Concrete action options** (not category labels). Use `preview` when comparing concrete artifacts (code snippets, config blocks, file-layout sketches).
- **Recommended option first** with "(Recommended)" — but only when one is genuinely defensible as the simplest-thing-that-works for the team's time budget + tech stack + spec.

**Do not write the plan file until this batch converges** — every design choice has a user-selected option. If the user's answer introduces a new sub-choice, ask that too before moving on.

**Step 2.4 — Write the plan file.**

Only after 2.3 converges, write the plan with these sections:

- **Increment summary** (1–2 sentences — what this increment delivers).
- **Anchor in SPEC.md** — which MVP acceptance criterion this advances + which sponsor requirement it satisfies, if any.
- **Files to touch / create** — exact list. New file paths spelled out.
- **Implementation approach** — the resolved approach from 2.3, described concretely (function names, route paths, schema shape).
- **Resolved decisions** — verbatim list of every `AskUserQuestion` round: question + user's chosen option. Every ≥2-option design choice must appear here.
- **Mechanical assumptions** — only items with no viable alternative (e.g., "the existing `tsconfig.json` already has `strict: true` — no choice to confirm"). Each carries a one-line justification.
- **Scope boundary for the implementor** — explicit "may touch" + "off-limits" lists.
- **Verification expectation** — what the implementor runs before reporting done. Default to the CLAUDE.md "Build / run / test" + the SPEC.md "Deploy command." Override per-increment if needed.
- **Deployable-state check** — the exact command that proves the project still works after this increment. Usually the dev / start / serve command from CLAUDE.md.
- **Out-of-scope follow-ups** — what came up during research that's *not* in this increment but worth tracking. Lands in SPEC.md "Out of scope" or "Open questions" after Phase 5.

A free-form `Assumptions` section is forbidden — that's the loophole this protocol fixes.

**Step 2.5 — Plan publication (optional, before `ExitPlanMode`).**

If the team wants peer review of the plan before implementation starts, fire `AskUserQuestion`:

- **Save plan to a file in the repo** — follow-up for the path (default: `docs/plans/<short-slug>.md`). Claude writes it; the dev pushes / shares however they like.
- **Drop the plan as a GitHub PR comment / Issue comment** — if the project has a remote and `gh` is authenticated, follow-up for the target PR / Issue number. Posts via `gh pr comment` / `gh issue comment`.
- **Skip** — proceed to `ExitPlanMode` immediately.

This is for teams who want to do design review before the implementor runs, separate from the dev's own approval at `ExitPlanMode`. Not the default.

**Step 2.6 — `ExitPlanMode`** for the increment plan approval. If the dev redirects, re-enter plan mode, update the plan file, `ExitPlanMode` again.

### Phase 3 — Implementation (`implementor` dispatch)

Dispatch one `implementor` agent at the project root. Hackathon projects are typically single-clone single-tree, so **only one implementor at a time** — even if the plan could theoretically split, sequential is safer in a small repo.

Dispatch contract (matches `.claude/agents/implementor.md` input):

- **Working directory path** — project root (or a subdirectory if the increment is scoped to one).
- **Task description** — the implementation approach from the plan, verbatim.
- **Acceptance criteria** — from the plan's "Anchor in SPEC.md" + the increment's specific completion shape.
- **Scope boundary** — exact "may touch" + "off-limits" lists from the plan.
- **Context brief** — the Phase 1 `context-gatherer` output, pruned to what's relevant for this increment.
- **Verification expectation** — from the plan.
- **Deployable-state check** — from the plan. The implementor will run this as part of self-verification.

**If the increment can be cleanly split into two genuinely independent file sets** (e.g., "add API endpoint" + "add UI button that calls it" — touching disjoint directories), the team may opt-in to a 2-agent split via `AskUserQuestion` before dispatch. Default to single-agent. Multiple agents in the same project dir is allowed only when the file sets are genuinely disjoint — never let two agents touch overlapping files.

When the implementor returns:
- Verify actual file changes against the summary (summaries can drift from reality).
- Confirm the deployable-state check ran and passed.
- Confirm sponsor integration depth was hit, if applicable.
- Surface "Open questions for the parent" to the dev before declaring done.

### Phase 4 — Verification (dev-driven, lightweight)

The implementor already ran the verification expectation + deployable-state check. This phase is for the **dev** to sanity-check that the increment matches intent — usually 2–5 minutes:

- Print: "Implementor done. Verified locally: build + tests + deploy-check passed. Take a look — run the deploy command yourself if you want, and tell me if anything's off."
- Wait for dev feedback.

**If the dev reports an issue:**
- For small fixes (typo, wrong copy, off-by-one): propose the fix via `AskUserQuestion` with the diff as `preview`, apply on approval. No re-plan.
- For scope-extension or design-redo: re-enter plan mode, update the plan with the redirect, re-dispatch implementor. Don't try to patch in chat.
- For "this is more bug-shaped than feature-shaped": offer `/debug` as a hand-off — print the suggested invocation and exit `/ship-it` cleanly.

**Exit Phase 4 only when the dev confirms** (via `AskUserQuestion` if it's ambiguous, or a clear "looks good" message). Don't move to wrap-up on assumption.

### Phase 5 — SPEC.md update (if needed)

Update `SPEC.md` if this increment changed any of:

- **MVP acceptance criteria** — one criterion is now met (mark with ✅ or move to a "Completed" section).
- **Out of scope** — research surfaced something explicitly excluded.
- **Open questions** — a previously-open question was answered, or a new one was opened.
- **Tech stack** — a previously-TBD choice was made.
- **Deployment** — the deploy command changed, or a new env var was added.

Edit `SPEC.md` directly via `Edit` (single source of project context — keep it current). If the increment didn't touch any of these, skip this phase.

### Phase 6 — Wrap-up + optional commit

1. **Print summary:**
   ```
   Increment <slug> shipped. Files changed: <list>. Verification: pass. Deploy check: pass.
   <Sponsor X> integration depth: verified per SPEC.md / N/A.
   SPEC.md updated: <yes — list sections / no>.
   Out-of-scope follow-ups: <list, or None.>
   ```

2. **Commit-after-verify prompt (optional).** Fire `AskUserQuestion`:
   - "Commit now — I'll help draft a message" (Recommended) — Claude reviews `git diff --stat` + `git diff`, proposes a message grounded in the actual changes, dev approves / edits, then runs `git add` (specific files only — never `-A`) + `git commit`.
   - "Commit now — I have a message in mind" — dev supplies the exact text; Claude runs `add` + `commit`.
   - "Skip — I'll commit later or merge into a bigger commit."

   When drafting the message: follow the project's commit style (check `git log --oneline -5`). For sponsor-touching increments, include the sponsor name in the body (helps with later submission-readiness audits).

3. **Push?** — Never auto-push. If the dev wants the increment up, they push themselves. Print the suggested command (`git push -u origin <branch>` for first push on a new branch, plain `git push` otherwise) but do NOT execute.

4. **Hand-off:** print "Ready for the next increment? `/ship-it` again, or if something's now bug-shaped, `/debug`."

## Cross-skill hand-offs

- **From `/debug`:** when `/debug`'s Phase 6 fix plan lands, it can hand back to `/ship-it` for the actual implementation (`/debug` does its own implementor dispatch in most cases — the hand-off is for *future* increments that build on the fix).
- **From `/pr-feedback`:** PR-feedback's address-thread implementor dispatches don't go through `/ship-it`. But if a reviewer comment spawns a real new increment ("we should also add X for completeness"), `/pr-feedback`'s deferral options include "Add to SPEC.md Open questions + plan via `/ship-it`."
- **To `/debug`:** if Phase 4's dev feedback reveals the increment surfaced a deeper bug, offer the hand-off and exit.

## What this skill does not do

- **Does not push to a remote.** Even when Phase 6 commits, push is the dev's call.
- **Does not deploy.** Per SPEC.md, deployment commands belong to the dev — Claude runs them only if explicitly told to.
- **Does not run dev servers indefinitely** (e.g., `npm run dev`). The deployable-state check is a *one-shot* command — `npm run build` or `python -m compileall` style.
- **Does not invent SPEC.md content.** If SPEC.md is missing or thin, the skill stops and points at `/kickoff`.
- **Does not skip the implementor and edit directly.** Every code change goes through the implementor agent. Even tiny changes — that keeps the audit trail clean.
- **Does not auto-create branches.** If the team is using feature branches, they create the branch before `/ship-it`. The skill respects whatever branch is currently checked out.

## Troubleshooting

- **`SPEC.md` missing** — Phase 1 Step 1a handles this. Recommend `/kickoff`.
- **Increment too big mid-implementation** — implementor reports "blocked — scope needs extension." Re-enter plan mode, split the increment into two, dispatch the first half.
- **Deployable-state check fails after implementation** — implementor should have caught this in self-verification. If it slipped through: re-enter Phase 4 with the failure as the issue. Don't ship a broken-deploy increment.
- **Sponsor integration depth not actually hit** — same as above; treat as "fix before declaring done."
- **`Agent type 'context-gatherer' not found` / `'implementor' not found`** — agents haven't loaded. Phase 1 has an inline fallback; Phase 3 does not — must restart the Claude Code session before continuing.
- **Mid-planning, research surfaces a new design option** — stop. Collect the option into 2.3's pending-decisions list and fire `AskUserQuestion`. Do not bake it into the plan as "tentative" — that's the exact anti-pattern non-negotiable #2 forbids.
- **Dev says "you assumed X"** — trigger non-negotiable #7. Re-surface X as a new `AskUserQuestion` round; check the plan file for any decisions that depended on the wrong assumption.
