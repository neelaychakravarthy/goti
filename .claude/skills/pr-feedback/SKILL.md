---
name: pr-feedback
description: Incorporate PR review feedback on the current hackathon project. Pulls PR metadata + review threads via gh, gathers spec context via context-gatherer, triages each comment with the team (address/reply/defer/dismiss/investigate), dispatches investigators for research and the implementor agent for approved changes, runs a local testing loop, then posts drafted replies and resolves validated threads. Plan-first with multiple approval gates; never pushes.
trigger: /pr-feedback
---

# /pr-feedback

Orchestrates PR review-feedback incorporation for a hackathon project. Uses `context-gatherer`, `investigator`, and `implementor` agents plus three approval gates — triage, testing, resolution.

Hackathon-tuned: assumes the PR is on the project's primary branch (no worktree juggling), assumes the team is small enough that triage is fast, and prioritizes shipping over exhaustive thread-by-thread arguing.

## Usage

```
/pr-feedback <PR-URL>                  # single PR
/pr-feedback <PR-NUMBER>               # if the project's git remote is set, just the number works
/pr-feedback --continue                # resume an in-flight session
```

`<PR-URL>` may be a full GitHub URL (`https://github.com/org/repo/pull/123`) or shorthand `org/repo#123`.

## Non-negotiables

1. **Never modify code before triage is approved.** Gather context → triage → research (if needed) → *wait for explicit approval* → then dispatch implementor.
2. **Never post replies or resolve threads without explicit approval.** Replies are drafted in Phase 4, approved in Phase 5 after testing, posted in Phase 6.
2a. **Only draft replies that are actually needed.** A reply is needed **only** when (a) the requested change is NOT being addressed (DISMISS / DEFER / REPLY), or (b) the requested change is being addressed **differently** than the reviewer suggested. For plain ADDRESS where the fix matches the reviewer's suggestion, **no reply** — the diff is the answer. Replies are written as **Claude, not impersonating the developer** ("I" is Claude). Concise, direct, detailed. No thanks-preamble, no apology, no filler.
3. **Never push.** The dev pushes. The skill prints suggested commands at the end of Phase 6.
4. **Never force-push.** If a reviewer asks for a history-rewriting change (squash, rebase), surface it as a dev decision; don't execute.
5. **Operate on the primary clone.** Hackathon projects don't use worktrees. Verify the PR's head branch is currently checked out (or guide the dev through checkout) before proceeding. Show the dev the current `git status` so dirty files are visible. **Never auto-checkout** — the dev decides.
6. **Never alter git state beyond implementor file edits.** No `commit`, `checkout`, `reset`, `stash`, `rebase`. Implementors edit; the dev stages, commits, pushes.
7. **Self-critique on missed assumptions.** If the dev says "you assumed X" or "you didn't ask about Y", acknowledge, re-surface the missed question as a new `AskUserQuestion` round with concrete action options.
8. **Interactive approvals use built-in tools, one card per question.** `AskUserQuestion` / `EnterPlanMode` / `ExitPlanMode` — never dump a long markdown document and ask for a bulk inline reply. Every per-card triage question must embed the reviewer's comment, a diff excerpt, and concrete action options (not category labels). Multiple cards = multiple sequential `AskUserQuestion` calls, never one collapsed bulk question.

## Interaction model

- **`EnterPlanMode` + `ExitPlanMode`** — for the overall triage plan (Phase 2), the implementation plan (Phase 4), and any moment where the dev approves a written artifact before mutations. `EnterPlanMode` opens the plan file where **draft** triage cards are written; `ExitPlanMode` is the **final** approval gate. Between, iterate with the dev via `AskUserQuestion` until every card is finalized.
- **`AskUserQuestion`** — for discrete choice points: per-card triage iteration, per-item re-categorization after investigation, per-fix approval in Phase 5, per-reply "resolve thread y/n" in Phase 6, dirty-file confirmations in Phase 1. Batch ≤4 per call. If more items need decisions, fire multiple `AskUserQuestion` calls sequentially.

**Anti-patterns (prohibited):**
- **Bulk inline markdown dump** — a 15-card triage doc in chat with "reply '1-3 ADDRESS, 4-5 REPLY, ...'" at the bottom.
- **One-shot `ExitPlanMode` on a monolithic triage plan** — writing every card to the plan file and calling `ExitPlanMode` immediately. The triage plan is a **draft**; iterate via `AskUserQuestion` first.

## Workflow

### Phase 1 — PR discovery + context (read-only)

1. **Resolve the invocation to a PR URL.**
   - **Explicit URL:** use it directly.
   - **Just a number:** read `git remote get-url origin` to derive `org/repo`; construct the URL.
   - **`--continue`:** re-fetch thread state for the previously-addressed PR. Ask the dev for the URL if conversation context is cold.

2. **Fetch PR metadata:**
   ```bash
   gh pr view <pr-url> --json number,title,body,headRefName,baseRefName,state,url,author
   ```
   Extract: head branch, base branch, PR state. If state isn't `OPEN`, stop and ask — addressing feedback on a closed PR is unusual.

3. **Verify the PR's head branch is checked out in the primary clone.**
   ```bash
   git -C <project-root> branch --show-current
   git -C <project-root> status --short
   ```
   - If the current branch matches the PR's head branch: surface the `git status --short` output, then `AskUserQuestion`: "Proceed in this working directory? Dirty files visible above." Options: "Proceed (Recommended)" / "Stop — something's wrong" / "Show me more (`git status -v`)".
   - If the current branch does NOT match: `AskUserQuestion`: "PR's head branch is `<X>` but current branch is `<Y>`. Options: I'll checkout `<X>` myself and retry (Recommended) / Use the current branch anyway (risky) / Abort."
   - Do NOT auto-checkout.

4. **Fetch review threads via GraphQL.** REST alone doesn't expose thread resolution state; GraphQL is required for `isResolved` and the `resolveReviewThread` mutation later:
   ```bash
   gh api graphql -F owner=<owner> -F name=<repo> -F number=<num> -f query='
     query($owner: String!, $name: String!, $number: Int!) {
       repository(owner: $owner, name: $name) {
         pullRequest(number: $number) {
           reviewThreads(first: 100) {
             nodes {
               id
               isResolved
               isOutdated
               path
               line
               startLine
               comments(first: 50) {
                 nodes {
                   id
                   databaseId
                   body
                   author { login }
                   createdAt
                   diffHunk
                 }
               }
             }
           }
         }
       }
     }'
   ```
   In-scope for triage: unresolved, non-outdated threads. Outdated threads surface separately and usually auto-categorize as DISMISS-outdated (ask to confirm).

5. **Fetch issue comments** (general PR discussion):
   ```bash
   gh api repos/<owner>/<repo>/issues/<num>/comments
   ```

6. **Dispatch `context-gatherer`** with:
   - **Purpose:** `"/pr-feedback: incorporating review on PR #<num>"`
   - **Focus symbols / files:** files named in review comments (union across threads).

   The gatherer pulls SPEC.md highlights, CLAUDE.md rules, and recent activity — so triage has structural grounding inline comments can't provide.

   **Skip this dispatch only when:**
   - Invocation is `--continue` (prior-session context already loaded), OR
   - The PR is ≤5 threads AND touches only files the current session has already read.

   "The reviewer comments look self-contained" is NOT a valid skip reason.

### Phase 2 — Triage (draft → per-card iteration → final approval gate)

Phase 2 produces a triage plan, **iterates on it per-card via `AskUserQuestion` until every card is finalized**, and only then fires the final `ExitPlanMode` gate. The plan file is a living draft during iteration — not a monolithic artifact for one-shot approval.

**Step 2.1 — Early-exit check** (before entering plan mode):

If the PR has zero unresolved threads and no substantive issue comments, announce "Nothing to triage — all threads resolved. Stopping." and exit.

**Step 2.2 — Enter plan mode and write the initial draft triage plan:**

Call `EnterPlanMode`. Inside, write the initial draft to the plan file:

```markdown
# Triage plan — PR #<num> (DRAFT — iterating)

**Stats:** N unresolved threads + M issue comments.
Suggested categorization: A ADDRESS / B REPLY / C DEFER / D DISMISS / E INVESTIGATE.

## PR #<num> — <title>

### Thread <N>: `<file>:<line>` — @<author>
- **Thread ID:** `<graphql-node-id>` (load-bearing — needed for Phase 6 resolution)
- **Comment DB ID:** `<databaseId>` (load-bearing — needed for Phase 6 reply posting)
- **Excerpt:** <root comment body, ~200 chars> [+ K replies, last @<user>]
- **Diff hunk:** 3–5 most relevant lines
- **Suggested categorization:** **<ADDRESS | REPLY | DEFER | DISMISS | INVESTIGATE>**
  - *Reasoning:* 1–2 sentences grounded in context brief / diff / thread.
- *If ADDRESS (matches reviewer's suggested fix):* **Proposed change** (file + approach), **Scope** (single/multi file). **Do NOT draft a reply** — the diff is the answer.
- *If ADDRESS but fix diverges from reviewer's suggestion:* **Proposed change**, **Scope**, **Draft reply** (as Claude; concise; explains divergence).
- *If REPLY:* **Draft reply** (as Claude; the substantive response).
- *If DEFER:* **Tracking** (SPEC.md "Open questions" / TODO.md / follow-up PR), **Draft reply** (short note explaining deferral).
- *If DISMISS:* **Reason** (outdated / intentional / already-addressed + citation), **Draft reply** unless DISMISS-outdated.
- *If INVESTIGATE:* **Question for investigator** (narrow, specific).

### ... (one card per thread and per substantive issue comment) ...

## Dispatch plan after final approval
- **Phase 3 investigators (parallel):** list of INVESTIGATE items
- **Phase 4 implementor:** list of ADDRESS items
- **Phase 4 reply drafts to prepare:** list of REPLY / DIVERGENT-ADDRESS / DEFER / contested-DISMISS items
```

For summary-comment reviews raising novel issues, treat each novel issue as its own card with a composite ID like `SC-<n>`.

**No free-form `Assumptions` section in the plan file.** Sub-choices are `AskUserQuestion` options in Step 2.3, not plan-file bullets.

**Do NOT call `ExitPlanMode` yet** — the plan is a DRAFT.

**Step 2.3 — Iterate per-card via `AskUserQuestion`:**

Walk through with the dev. Converge on every card's categorization + proposed resolution + (if present) draft reply before any final gate.

- **One card per question.** Batch up to 4 per `AskUserQuestion` call. For >4 cards, fire multiple sequential calls. Never collapse into a single bulk question.
- **Apply every dev decision to the plan file immediately** via `Edit` (plan mode allows editing the plan file). Don't accumulate decisions in chat.
- **Keep iterating** until every card has been explicitly decided.

**Required question shape for every per-card question:**

- `question` text must include:
  - **File path and line number**
  - **Reviewer's comment body itself** — verbatim when short, faithful 2–3 sentence paraphrase when very long. Don't reduce to "the reviewer flagged an NPE" — quote enough that the dev reads the actual concern.
  - **Short diff-hunk excerpt** (2–5 lines around the commented line).
  - **Your concise reasoning** (1–2 sentences) for the suggested categorization.
- `options` must be concrete actions, not generic category labels:
  - ✅ "Apply reviewer's suggested fix (Recommended)" — with a `preview` of the fix
  - ✅ "Apply alternative fix — I'll describe"
  - ✅ "Reply explaining why no change is needed"
  - ✅ "Defer to SPEC.md Open questions / follow-up PR"
  - ✅ "Dismiss — intentional / out of scope"
  - ✅ "Investigate first — <specific narrow question>"
  - ✅ "Defer to `/debug` — reviewer flagged a latent bug needing RCA"
  - ❌ "ADDRESS" / "REPLY" / "DEFER" / "DISMISS" / "INVESTIGATE" on their own
- **Use `preview`** on the recommended option when showing reviewer-suggested code, your proposed alternative diff, or the draft reply text.

**Forbidden patterns:**
- ❌ One-summary-question-per-PR ("Cards T1 through T6: confirm all ADDRESS?").
- ❌ Terse questions citing only thread IDs without comment body and reasoning.
- ❌ Stacking unrelated cards into a single `multiSelect` question.
- ❌ Skipping iteration and firing `ExitPlanMode` immediately.
- ❌ Single "does the plan look good?" question covering the whole document.

**Narrow shortcuts that are OK:**
- **Tightly-bundled pairs** — two cards that must resolve together (e.g., identical fixes mirrored across two sites) can share a single question, explicitly named as a bundle, with both comment bodies cited inline.
- **Dev-issued blanket directives** — "address all Copilot suggestions as-is unless you flag one" — honor without re-asking. The directive must come explicitly.

**Step 2.4 — `ExitPlanMode` for the final approval gate:**

Only after iteration converges, update the plan file header to remove the `(DRAFT — iterating)` suffix, call `ExitPlanMode`. This is the **final** approval gate.

**Step 2.5 — Handling post-gate redirects:**

If the dev redirects after the final gate, re-enter plan mode, apply the redirects, `ExitPlanMode` again. Don't patch approvals in chat.

**Do not proceed to Phase 3 until final `ExitPlanMode` is approved.**

### Phase 3 — Investigation (parallel where possible)

For each thread categorized INVESTIGATE, dispatch the `investigator` agent. Fire all independent investigators in a single message so they run concurrently.

Each dispatch includes:
- **Question:** thread's root comment + any context the dev added during triage
- **Location:** file + region + diff hunk
- **Decision the human needs to make:** "decide: address / reply / dismiss / defer"
- **Context pointers:** slice of Phase-1 `context-gatherer` brief relevant to this question

When findings return, finalize each thread's categorization via `AskUserQuestion` — one question per investigated thread, batched ≤4 per call:
- **question:** "Thread <N> (`<file>:<line>`) investigation: <one-line finding>. Finalize as?"
- **options:** ADDRESS / REPLY / DEFER / DISMISS (2-3 plausible outcomes based on the investigator's proposed decision; recommended first with rationale).

Surface the investigator's "Proposed decision" + "Confidence" + "What would override me" in the question text.

If any categorization changes, briefly re-enter plan mode to update the triage plan file (only the changed subset), then `ExitPlanMode` for a light re-approval.

### Phase 4 — Implementation + reply drafting

**For ADDRESS threads:** dispatch one `implementor` at the project root. (Multiple implementors only if the changes are genuinely disjoint file sets — same constraint as `/ship-it`.)

Implementor dispatch includes:
- **Working directory path:** project root.
- **Task description:** `"Address PR review comments on PR <url>: <list of thread IDs + approved resolutions>"`
- **Acceptance criteria:** one criterion per thread — the approved "Proposed change" from triage. If an investigator refined it, use the refined version.
- **Context brief:** pruned Phase 1 `context-gatherer` output + any investigator findings.
- **Scope boundary:** exactly the files/modules the approved changes touch. **No drive-by refactors during PR feedback.**
- **Verification expectation:** run the project's test / lint / build commands from CLAUDE.md for the changed area. If no tests exist, report that; Phase 5 testing is the real verification.
- **Deployable-state check:** as always, the increment must leave the project deployable.

**For threads that carry a drafted reply** (REPLY, DEFER, contested DISMISS, ADDRESS-with-divergence): confirm reply text via `AskUserQuestion`, one question per reply, batched ≤4 per call. Each question's options: "Approve as drafted (Recommended)" / "Edit — I'll provide the text" / "Skip this reply". Include the full draft text in the question or as a preview. Do NOT post yet — replies post in Phase 6 after testing.

**Plain ADDRESS threads (fix matches reviewer's suggestion) have NO drafted reply** and are NOT in this step. Their resolution is the diff; Phase 6 resolves the thread after validation. Do not invent a reply "to be polite" — it's noise in the reviewer's notifications.

**`/debug` deferral threads** (triage chose "Defer to `/debug`"): draft a reply as Claude noting the deferral:

> "This needs root-cause analysis before a fix is safe — handling via `/debug` in a separate PR. Tracking: <SPEC.md Open questions entry / follow-up PR>. Will link the fix PR back here when it's ready."

The dev then runs `/debug` in a fresh turn after `/pr-feedback` completes. The deferral thread is **not resolved** by Phase 6 — the dev re-opens `/pr-feedback` when the `/debug` fix lands.

**Reply voice enforcement:** All drafted replies are written as **Claude**. "I" always refers to Claude, never the dev. Concise, direct, detailed. No "Thanks for catching this!" preamble. No apologies. No filler. If a draft reads like it could have been written by the dev, rewrite it — the reviewer should know it's an assistant reply.

**Review implementor summary** when it returns. Verify file changes against the summary. Surface findings as a wrap-up: re-enter plan mode briefly, write a Phase-4 summary plan (implementor results, any scope-extension requests, the approved reply drafts), and `ExitPlanMode` to get sign-off before Phase 5. For simple cases, a one-paragraph text summary + `AskUserQuestion("Ready to start the Phase-5 testing loop?", ["Yes", "No — something to address first"])` is acceptable.

### Phase 5 — Local testing loop (dev-driven)

Tell the dev: "Changes are in the working tree. Test locally (run dev server, run tests, manual check). Come back with errors or anything that doesn't match intent."

Loop:
- Dev reports an error, unexpected behavior, or concern.
- Diagnose: read the worktree files; dispatch `investigator` for complex "is this approach correct" questions.
- **Propose fix via `AskUserQuestion`.** Options: "Apply the proposed fix (Recommended)" / "Different approach — I'll describe" / "Skip — undo the original change instead" / "Investigate further". Include the proposed fix as a code `preview`.
- For non-trivial refinements: re-enter plan mode, write the refined scope as a small plan, `ExitPlanMode`, re-dispatch implementor.
- Re-verify where possible.
- Ask the dev to confirm validation before leaving the loop. `AskUserQuestion`: "Validated — proceed to Phase 6 / Still testing / Something broke — new issue to address."

**When testing reveals a change should not ship as-is:**
- If the underlying thread's categorization was wrong, revert the relevant implementor edits via `Edit` (restore previous content — dev hasn't committed yet) and re-triage that thread (DISMISS / REPLY / DEFER). Redraft the reply.
- Never leave half-applied changes.

### Phase 6 — Post replies + resolve threads

Only after the dev explicitly confirms validation:

1. **Post approved replies.**

   **Review-comment replies** (threads attached to a diff line) — REST endpoint with `in_reply_to` taking the comment's `databaseId`:
   ```bash
   gh api repos/<owner>/<repo>/pulls/<num>/comments \
     -f body="<reply-text>" \
     -F in_reply_to=<comment-databaseId>
   ```

   **Issue-comment replies** (general PR discussion):
   ```bash
   gh pr comment <pr-url> --body "<reply-text>"
   ```

2. **Resolve threads** via GraphQL `resolveReviewThread` mutation:
   ```bash
   gh api graphql -F threadId=<thread-graphql-id> -f query='
     mutation($threadId: ID!) {
       resolveReviewThread(input: { threadId: $threadId }) {
         thread { id isResolved }
       }
     }'
   ```

   **Default resolution rules:**
   - ADDRESS-validated, fix matches reviewer's suggestion: resolve — **no reply** is posted.
   - ADDRESS-validated, fix diverges: post the drafted divergence-explanation reply, then resolve.
   - REPLY-posted (no code change): resolve (default) — unless the reply contests the reviewer's position, then leave open.
   - DEFER: post the drafted deferral note, leave open unless the dev says to resolve.
   - DISMISS-outdated: resolve silently — no reply.
   - DISMISS-contested: do **not** resolve on the reviewer's behalf. Post the explanation; leave the thread open.

   **For ambiguous cases**, use `AskUserQuestion` per thread — options "Resolve / Leave open / Leave open + add tracking comment" — batched ≤4 per call.

3. **Report summary:**
   - Threads resolved: count + list
   - Threads replied but not resolved: count + list (with reason)
   - Threads still open: count + list (with reason)
   - **Suggested push commands** (do not execute):
     ```
     cd <project-root>
     git status
     git add <changed-files>           # specific files only — never -A
     git commit -m "<suggested-msg>"   # draft based on approved changes
     git push
     ```
     If other dirty files were present, **explicitly list which files to `git add`** so the dev doesn't accidentally commit unrelated changes. Never suggest `git add -A`.

4. **Do NOT push.** Print the commands; the dev runs them.

## What this skill does not do

- **Does not push.** Dev pushes.
- **Does not auto-checkout the PR's head branch.** Phase 1 guides the dev through the checkout if needed.
- **Does not invoke `/debug` for "Defer to `/debug`" threads** — the dev runs `/debug` in a fresh turn after `/pr-feedback` exits.
- **Does not merge the PR.** Dev's call.
- **Does not skip the implementor and edit directly.** Every code change goes through implementor — clean audit trail.

## Troubleshooting

- **`gh` not authenticated** — stop. Print `gh auth login` for the dev to run.
- **PR's head branch isn't checked out** — Phase 1 guides the dev through it; never auto-checkout.
- **PR branch was force-pushed since a reviewer's comment** — `line`/`startLine` may no longer match the current file. Use `diffHunk` from the thread as source of truth for location. Flag outdated threads.
- **Review comment on code that no longer exists (`isOutdated: true`)** — triage as DISMISS-outdated by default; confirm with the dev.
- **Reviewer asked for a history-rewriting change (squash, rebase, force-push)** — do not execute. Surface as a dev decision; propose a reply explaining that force-push work isn't done by this skill.
- **`Agent type 'context-gatherer' / 'investigator' / 'implementor' not found`** — restart Claude Code.
- **Implementor reports "blocked — scope needs extension"** — re-triage that thread with the dev (expand scope or change category), re-dispatch.
- **Implementor summary contradicts actual file changes** — trust the files. Flag the discrepancy; investigate.
- **Dev says "you assumed X"** — trigger self-critique: pause, note the missed question, review already-approved triage / changes for the wrong assumption, re-surface affected cards.
