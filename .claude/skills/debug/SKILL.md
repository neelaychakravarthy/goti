---
name: debug
description: RCA-first bug-fix loop for hackathon projects. Iteratively investigates with the dev (narrow code probes + dev-run runtime probes + gated speculative fixes) until the root cause is confirmed, then plans + implements the fix via the implementor agent. Every diagnostic action is dev-approved; the dev controls the investigation tree. Lighter and faster than a full-engineering bugfix loop — designed for the hackathon time budget.
trigger: /debug
---

# /debug

Drives the bug-fix arc when a defect needs root-cause analysis before a fix is safe to plan. Unlike `/ship-it`, which plans-then-implements a well-scoped change, `/debug` begins with an open-ended diagnostic loop and only moves to planning once the root cause is confirmed.

Tuned for hackathon speed: every probe is small, the loop should converge in ≤5 rounds for typical bugs, and the fix scope is small-and-shippable rather than "best-practice."

## Usage

```
/debug                                # interactive — skill asks what's broken
/debug "<bug description>"            # seeded with a description
/debug --fast-path                    # team claims the root cause; skill validates and plans
/debug --continue                     # resume an in-flight session (RCA state restored)
```

## Non-negotiables

1. **Never modify code before the root cause is confirmed AND the fix plan is approved.** Two separate approval gates: Phase 3's RCA confirmation and Phase 6's plan approval.
2. **Speculative fixes are permitted only with dev approval per fix, only when testable locally, and reverted in the same turn if the hypothesis is rejected.** A speculative fix is a diagnostic probe, not a partial implementation.
3. **Every diagnostic action is dev-gated.** Dispatching an investigator, asking the dev to add a log line, asking the dev to run a reproduction command, proposing a speculative edit, running a test — each goes through `AskUserQuestion` first. The dev controls which branch of the investigation tree to go down.
4. **Never alter git state without explicit approval.** No `commit`, `branch`, `checkout`, `reset`, `stash`, `rebase`. The implementor in Phase 7 edits files without mutating git.
5. **Hackathon time is real.** Soft rhythm check at round 5: if RC isn't confirmed, surface "we've been at this 5 rounds — want to keep going, reframe, or escalate to a teammate?" Round 10: same prompt, stronger.
6. **Self-critique on missed assumptions.** If the dev says "you assumed X" or "you skipped a hypothesis", acknowledge, re-surface X as a new `AskUserQuestion`, and check whether rejected hypotheses need re-opening. Do not silently patch the course.
7. **Interactive approvals use built-in tools.** `AskUserQuestion` for per-round and per-probe decisions. `EnterPlanMode` / `ExitPlanMode` for the Phase-6 fix plan. Never dump hypotheses in chat and ask for a bulk reply.

## Interaction model

Two primary tools:
- **`AskUserQuestion`** — every diagnostic decision, every speculative edit, per-round check-ins. Batch ≤4 per call. Use `preview` for concrete artifacts (proposed log line, proposed fix diff).
- **`EnterPlanMode` / `ExitPlanMode`** — Phase 6 fix-plan approval gate, same shape as `/ship-it` Phase 2.

Anti-patterns (both prohibited):
- **Unilateral investigation tree choices** — picking the next probe without an `AskUserQuestion` and just dispatching. The dev's answer to "next probe: A or B" sometimes reveals context the RCA summary didn't have.
- **Bulk hypothesis dump followed by "which one should I chase?"** — pick the most promising hypothesis yourself, recommend it with rationale, and ask in `AskUserQuestion` options. Don't offload the judgment call to the dev's free-text answer.

## Workflow

### Phase 0 — Upfront framing

One `AskUserQuestion` call with up to 4 questions batched, resolving the preconditions.

**Q0.1 — Nature of work.** Options (set dynamically from detected state):
- "New bug — I'm on `<detected-branch>` and want to investigate from here."
- "Continuation — I started investigating earlier; let me share what I have so far."
- "Different — let me describe" (free-form).

**Q0.2 — Starting evidence bundle.** Free-text prompting the dev to include: bug description, observed vs expected behavior, reproduction steps, any logs / stack traces, initial hypotheses (if any), and specific files / symbols they suspect.

**Q0.3 — Fast-path?**
- "Run full RCA (Recommended when uncertain)"
- "Fast-path — I already know the root cause; validate and plan" — requires the RC statement in the answer.
- "Fast-path — I know the RC AND the fix approach; go straight to plan after validation."

If fast-path is chosen, require the dev's RC statement to be captured. Without it, default to full RCA.

### Phase 1 — Context gathering

Dispatch `context-gatherer` with:
- **Purpose:** `"/debug RCA seed: <one-line bug description from Q0.2>"`
- **Focus symbols / files:** files mentioned in the evidence bundle, if any.

Feed the brief into Phase 2's state block. If the brief surfaces context gaps blocking the first probe (e.g., missing reproduction steps), resolve via `AskUserQuestion` before starting the loop.

### Phase 2 — Diagnostic investigation (iterative)

A **loop** with explicit state, not a linear sequence. Every probe type is dev-gated.

#### Skill state (maintained across rounds; re-surfaced on `--continue`)

Re-render a compact version at the top of every round's chat turn so the dev can see the trajectory:

```
Bug: <one-line summary>
Evidence bundle (Phase 0): <summary>

Hypotheses:
  H1 (active, conf: medium): <statement>
  H2 (ruled out, round 2): <statement> — because <evidence E3>
  H3 (active, conf: low): <statement>

Evidence (numbered):
  E1 (round 1, investigator): <finding, citing file + symbol>
  E2 (round 2, dev runtime check): <observation>
  E3 (round 2, code read): <finding>

Ruled out:
  - <thing> — evidence E<N>

Next probe (proposed): <one sentence>
```

#### Round loop

1. **State the hypothesis.** One sentence at the top of the round, with confidence band. If >1 active, pick the most promising and say why.

2. **Propose the next probe.** One probe per round. Types:

   - **Code-reading probe** — dispatch `investigator` with a narrow question derived from the hypothesis. `AskUserQuestion`: "Dispatch investigator: `<exact question>`? Options: Yes (Recommended) / Refine the question — I'll edit / Skip — pick a different direction / Pause."
   - **Runtime probe (dev runs)** — `AskUserQuestion` asking the dev to execute one concrete action:
     - "Add this log line at `<file>:<region>` and run `<reproduction command>` — paste the relevant output when done" (log text in `preview` on Recommended)
     - "Run this in your local shell and paste the output: `<command>`"
     - "Check the value of `<env var>` / `<config key>` in your `.env`"
     - "Set a breakpoint at `<file>:<region>`, reproduce, paste the frame state"
     - Alt options: "Skip — I'll describe what I've already seen" / "Run a different probe — I'll describe"
   - **Speculative-fix probe** — `AskUserQuestion` with the proposed edit as `preview`. Options: "Apply and test locally" / "Apply and DON'T revert — keep as partial progress" / "Skip — too risky / too speculative" / "Different edit — I'll describe". **Default policy: if applied-and-test and the hypothesis is rejected, the edit is reverted in the same turn; if confirmed, it becomes a candidate for the fix plan.** "Don't revert" is the dev's explicit opt-out.
   - **Test-run probe** — `AskUserQuestion`: "Run `<command>` (Recommended)" / "Different command — I'll provide" / "Dev runs it and reports" / "Skip tests this round."

3. **Integrate the result.** Update skill state — append new evidence, mark hypotheses as confirmed / ruled out / refined, update confidence. If a speculative fix was applied-and-rejected, revert before proceeding.

4. **End-of-round check-in.** `AskUserQuestion`:
   - "Next probe: `<proposed>` (Recommended)"
   - "Redirect — I want to test hypothesis `<H<N>>` instead"
   - "Redirect — new hypothesis: `<dev describes>`"
   - "We have the root cause — proceed to Phase 3"
   - "Pause — I'll resume with `/debug --continue` later"
   - "Abort — this isn't worth pursuing"

#### Soft rhythm checks

- **Round 5:** surface "we've been at this 5 rounds — want to reframe, escalate to a teammate, or keep going?" as an additional option on the end-of-round check-in.
- **Round 10:** stronger ("consider whether this is the right branch — we may have wandered"). If after round 15 the dev hasn't either reached RC or aborted, suggest pausing and asking a teammate or re-running context-gathering from scratch.

#### Fast-path variant (Phase 2)

If Q0.3 was fast-path, Phase 2 runs a **shorter validation loop**:

1. State the dev-claimed RC verbatim at the top of state block as "Claimed RC (unvalidated)".
2. Dispatch 1–2 narrow `investigator` probes:
   - "Does the code at `<claimed RC location>` actually behave as described?"
   - "Are there other call sites or conditions that would show the same symptom?"
3. If "RC known + fix approach known", add a probe validating the proposed fix's blast: "If we change `<X>` to `<Y>`, what else depends on the current behavior? (grep callers.)"
4. `AskUserQuestion` after validation:
   - "Validation confirms (Recommended) — proceed to Phase 3"
   - "Validation revealed a refinement — `<short description>`. Update the RC and proceed / open full RCA to re-examine."
   - "Validation contradicts the claimed RC — fall back to full RCA."

### Phase 3 — Root cause confirmation

When the dev signals "we have the root cause," write an RCA summary in chat:

```markdown
## Root cause

<1–2 sentence statement — what the RC is>

**Symptom → cause chain:**
1. <observed symptom>
2. <proximate cause, citing evidence E<N>>
3. <underlying root cause, citing evidence E<N>>

**Evidence supporting:**
- <bullet list of key evidence — not every E<N>, the ones that matter>

**What was ruled out:**
- <bullet list of rejected hypotheses + why>

**Affected scope:**
- Files / symbols: <list>
- Sponsor-touching? <yes/no — flag if it affects a SPEC.md sponsor requirement>

**Confidence:** <low / medium / high> — <one-line justification>
```

`AskUserQuestion`:
- "Confirm as stated — proceed to Phase 4 (Recommended)"
- "Partial — investigate sub-question `<X>` further" → back to Phase 2
- "Wrong track — redirect" → back to Phase 2, resetting relevant hypotheses
- "Confirmed, but don't plan a fix right now — log the finding and exit" → Phase 8 with no Phase 4–7

### Phase 4 — SPEC.md / TODO impact check

If the bug affects something documented in SPEC.md (a sponsor integration, a deploy command, a tech-stack assumption), surface it: `AskUserQuestion`:
- "Update SPEC.md 'Open questions' with the finding" — Claude drafts the update, dev approves.
- "Update SPEC.md elsewhere — specify which section" — follow-up.
- "Skip — pure code-level bug, doesn't affect spec."

For purely-internal bugs (no spec impact), skip this phase silently.

### Phase 5 — Branch / working-dir resolution

Hackathon projects typically work on a single primary clone. Default: investigate and fix on whichever branch the dev was on in Phase 0. Confirm via `AskUserQuestion`:
- "Fix on current branch `<branch>` (Recommended)"
- "Switch to a fix branch (`bugfix/<short-slug>`) before planning" — Claude prints the suggested commands; the dev runs them.
- "Different — I'll describe."

This is dev-driven; Claude doesn't checkout branches. If "Switch to a fix branch" is chosen, the skill pauses until the dev confirms the checkout is done.

### Phase 6 — Fix plan (plan-mode approval gate)

Same shape as `/ship-it` Phase 2, short version:

1. **Pre-finalize `AskUserQuestion` rounds** for any design choice with ≥2 viable options (fix approach, test additions, refactor-or-not, scope boundary). Each question: context, concrete options (not category labels), recommended option first with rationale, `preview` on comparison-worthy choices.
2. **`EnterPlanMode`** and write the plan:
   - **Root cause** (verbatim from Phase 3)
   - **Fix approach** (resolved via 6.1)
   - **Files to touch / create** (predicted)
   - **Regression check** (required — every bug fix verifies the bug stays fixed; if the team is willing, add a small test; otherwise the dev's runtime check is the regression check). The dev can opt out of writing a test via `AskUserQuestion` with a justification — hackathon time budget often forces this trade-off.
   - **Verification expectation** — typically the project's test command from CLAUDE.md.
   - **Deployable-state check** — same as `/ship-it`; the fix must leave the project deployable.
   - **Resolved decisions** — every Phase-6 `AskUserQuestion` round captured.
   - **Mechanical assumptions** (same rules as `/ship-it`: only no-viable-alternative items).
   - **Sponsor impact** — if any.
3. **`ExitPlanMode`** — approval gate.

### Phase 7 — Implementation

Dispatch `implementor` at the project root with the plan's contract:
- Working directory path
- Task description + acceptance criteria
- Context brief (pruned Phase-1 + Phase-2 evidence + Phase-3 RCA summary)
- Scope boundary (no drive-by refactors)
- Verification expectation
- Deployable-state check

When the implementor returns: verify file changes against the summary, confirm regression check ran, confirm deployable state preserved.

### Phase 8 — Wrap-up

Print:
- **Root cause** (one-line recap)
- **Branch + files changed**
- **Regression check status**
- **Verification + deployable-state result**
- **SPEC.md update status** (if any)
- **Optional commit prompt** — same shape as `/ship-it` Phase 6: dev-approved message, `git add <specific-files>` + `git commit`, never `-A`, never push.
- **Next-step suggestion:** `git push` when ready (printed, not executed).

## Cross-skill hand-offs

`/debug` is invokable from other skills when appropriate:

- **From `/ship-it`:** if Phase-4 dev feedback reveals the increment surfaced a deeper bug than expected, `/ship-it` offers `/debug` as a hand-off — print the suggested invocation and exit.
- **From `/pr-feedback`:** if a reviewer's comment surfaces a latent bug that needs RCA, the triage flow offers `/debug` as a deferral option on that card.

These are explicit dev choices, not automatic transitions. When the dev picks the hand-off, the calling skill exits cleanly; the dev runs `/debug` in a fresh turn.

## What this skill does not do

- **Does not push.** Even if Phase 8 commits, the dev pushes themselves.
- **Does not auto-checkout fix branches.** Branch ops are the dev's call.
- **Does not write tests against the dev's wishes.** Phase 6's regression check is opt-in for tests; if the dev says "no test, my own runtime check is the regression check," the plan respects that.
- **Does not invoke `/bugfix` recursively or auto-transition to `/ship-it`** at completion. The dev picks the next skill.

## Troubleshooting

- **Phase 2 hits 10+ rounds without converging** — soft rhythm check fires. `AskUserQuestion`: pause / reframe / escalate / keep going / abort. Don't push through silently.
- **Evidence is contradictory between probes** — state the contradiction explicitly and `AskUserQuestion`: "E3 says X, E5 says Y. Options: run E3 again (flakiness?) / test edge case Z / dev inspects raw state."
- **Speculative fix applied, dev forgot to say revert-or-keep** — default is revert. State this in the end-of-round check-in.
- **Fast-path validation contradicts the dev's claim** — don't argue. Pivot to full Phase 2 with the claimed RC recorded as "H1 (dev-proposed, unvalidated)" and refine. The dev may still be right — single probe can mislead.
- **`Agent type 'context-gatherer' / 'investigator' / 'implementor' not found`** — custom agents didn't load. `/debug`'s loop depends on all three. Stop and ask the dev to restart Claude Code.
- **Dev says "you assumed X"** — trigger non-negotiable #6. Re-surface X as a new `AskUserQuestion`. Revisit hypotheses that depended on the wrong assumption.
