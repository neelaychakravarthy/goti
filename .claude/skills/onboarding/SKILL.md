---
name: onboarding
description: Emit a styled walkthrough of the hackathon Claude harness — how /kickoff scaffolds a new project, how /ship-it drives spec-anchored incremental development, the gated-approval safety model, the agent stack, and the SPEC.md-as-source-of-truth convention. Use to onboard a new team member or re-anchor mid-hackathon when context drifts.
trigger: /onboarding
---

# /onboarding

A one-shot static walkthrough of the hackathon harness. Invoke when a teammate joins partway through, or when you want to re-anchor on what each skill does before picking up the next increment.

## Usage

```
/onboarding
```

## Workflow

1. Emit the Walkthrough section below verbatim. Do not invoke other tools, fetch live state, modify the content based on conversation context, or paraphrase — output the rendered markdown as-is so the team gets a consistent reference each time.

---

## Walkthrough

# Hackathon × Claude Code

A small, opinionated harness for shipping hackathon projects with Claude Code. Everything here is **static reference** — it explains how the system you're inside actually works.

---

## The shape of the work

```
   /kickoff --spec-only    /kickoff --start         /ship-it (×N)             /pr-feedback / /debug
   (pre-hackathon)         (hackathon day)             │                            │
       │                          │                    ▼                            ▼
       ▼                          ▼              ┌──────────┐              ┌──────────────────┐
  ┌──────────────┐         ┌─────────────┐       │ SPEC.md  │  ── reads ──▶│ Plan → implement │
  │ Interview +  │         │ Read SPEC,  │       │ +        │              │ → verify → wrap  │
  │ scaffold     │ ───────▶│ git init,   │ ─────▶│ CLAUDE.md│              │                  │
  │ NO git init  │         │ first commit│       └──────────┘              └──────────────────┘
  └──────────────┘         └─────────────┘            ▲
                                                      │ updates each increment
                                                      │
                                                /ship-it Phase 5
```

**SPEC.md is the source of truth.** Every skill reads from it; `/kickoff` writes the initial version; `/ship-it` updates it after each increment. If the spec drifts from reality, you have a bug.

**Two-phase kickoff is supported but optional.** If you want to plan ahead of the hackathon, use `/kickoff --spec-only` to write the spec without committing anything. Then `/kickoff --start` on hackathon day does git init + first commit. If you'd rather plan and start coding the same day, plain `/kickoff` does both phases in one go.

---

## The skills

| Skill                  | When to use                                                                      |
|------------------------|----------------------------------------------------------------------------------|
| `/kickoff --spec-only` | Pre-hackathon planning: interview + scaffold, **no git init**                    |
| `/kickoff --start`     | Day-of: read existing SPEC.md, do git init + first commit                        |
| `/kickoff` (no flag)   | Same-day flow: interview + scaffold + git init in one shot                       |
| `/ship-it`             | Plan + implement the next increment toward MVP. Run this many times              |
| `/debug`               | RCA-first bug-fix loop when the root cause isn't already known                   |
| `/pr-feedback`         | Triage + address PR review comments (if the team is using PRs)                   |
| `/skill-create`        | Add a new project-local skill mid-hackathon                                      |
| `/agent-create`        | Add a new project-local subagent mid-hackathon                                   |
| `/onboarding`          | This walkthrough                                                                 |

Type `/<skill-name>` to invoke. Each skill explains itself before doing anything destructive.

---

## The lifecycle

```
                     ┌──────────────────────────────────────────────────────┐
                     │                                                      │
                     │   Pre-hackathon (optional):                          │
                     │   1.  /kickoff --spec-only                           │
                     │       interview → SPEC.md + CLAUDE.md + .claude/     │
                     │       (no git init yet)                              │
                     │                                                      │
                     │   Hackathon day:                                     │
                     │   2.  cd <project> && claude                         │
                     │   3.  /kickoff --start                               │
                     │       confirm SPEC.md → git init + first commit      │
                     │                                                      │
                     │   Build loop:                                        │
                     │   4.  /ship-it     ← plan + implement one slice     │
                     │       (test)                                         │
                     │       /debug       ← if something breaks            │
                     │       /pr-feedback ← if the team uses PRs           │
                     │                                                      │
                     │   5.  /ship-it again until MVP acceptance hits      │
                     │                                                      │
                     │   6.  demo / submit                                  │
                     │                                                      │
                     └──────────────────────────────────────────────────────┘
```

If you don't pre-prep, plain `/kickoff` (no flag) replaces steps 1 + 3 with a single same-day invocation.

`/kickoff` runs once (or twice across phases). `/ship-it` runs many times. The MVP is hit when every acceptance criterion in `SPEC.md` is satisfied.

---

## Gated approvals — the safety model

Claude makes **plans, not assumptions**, and **asks, not assumes**. Every meaningful action passes through one of three gates.

```
   ┌───────────────────┐       ┌────────────────────┐       ┌──────────────────────┐
   │   EnterPlanMode   │ ───▶  │    ExitPlanMode    │ ───▶  │   AskUserQuestion    │
   │  (read-only mode, │       │  (plan approval —  │       │  (per-action gate —  │
   │   no edits, no    │       │   direction only,  │       │   git write, push,   │
   │   git mutations)  │       │   not git writes)  │       │   PR open, etc.)     │
   └───────────────────┘       └────────────────────┘       └──────────────────────┘
```

| Gate type              | Tool                          | Typical use                                                |
|------------------------|-------------------------------|------------------------------------------------------------|
| Read-only exploration  | (plan mode, default)          | Phase 1 of any plan-gated skill — context gathering        |
| Direction approval     | `ExitPlanMode`                | "Here's the plan; approve to leave plan mode"              |
| Per-action approval    | `AskUserQuestion`             | Branch create, commit, push, file write, destructive op    |
| Design clarification   | `AskUserQuestion` (in-phase)  | "Which of these 2 viable approaches?" before scaffolding   |

**Core principles baked into every plan-gated skill:**

- **Zero assumptions** — every design choice with ≥2 viable options surfaces as `AskUserQuestion` before the plan is finalized.
- **Never alter git state without explicit approval** — `stash`, `reset`, `checkout`, `restore`, `clean`, `commit`, `rebase`, `cherry-pick`, force-push, amend are all gated.
- **Investigate before destroying** — unfamiliar files / branches / lock files get inspected, not overwritten.
- **Hackathon time is real** — when a question has a "simplest path that works" option, that option is recommended unless the team has explicitly chosen quality over speed.

---

## SPEC.md — the canonical project context

Every downstream skill reads `SPEC.md` at the project root. It captures the **commitments** the team made at kickoff, plus the moving parts that update as you build:

```
SPEC.md
├── Project summary
├── Event context              (hackathon, time budget, demo requirements)
├── Required sponsors          (load-bearing — submission depends on this)
├── Deployment                 (target + command + env vars)
├── Tech stack                 (frontend / backend / DB / auth / AI)
├── MVP acceptance criteria    (the "done" definition)
├── Out of scope               (explicit non-goals — fights scope creep)
├── Open questions             (re-surfaced by /ship-it on round 2)
└── Other hard constraints     (anything else load-bearing)
```

**Keep it current.** Every `/ship-it` increment updates the sections it changed (acceptance criteria met, scope items added, questions answered). If the code drifts from SPEC.md, something has gone wrong — fix the spec OR fix the code, don't let them disagree.

---

## CLAUDE.md — project-root rules

A small companion to SPEC.md that holds **rules** (vs. spec content):

```
CLAUDE.md
├── Project context              (1-line + "always read SPEC.md first")
├── Build / run / test / deploy  (the commands)
├── Git policy                   (never alter without approval)
├── Conventions                  (no drive-by refactors, sponsor reqs are load-bearing)
└── Available skills             (the catalog)
```

If `/kickoff` scaffolded this for you, it's already populated from the interview answers. Edit it when conventions evolve.

---

## The agent stack

Skills orchestrate; subagents do bounded specialist work in isolated context windows. Each has a declared tool allowlist and structured output contract.

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │   Skills (/kickoff, /ship-it, /debug, /pr-feedback)              │
  │       │                                                          │
  │       ▼ dispatch via Agent tool                                  │
  │                                                                  │
  │   ┌────────────────┐  ┌──────────────┐  ┌──────────────┐        │
  │   │context-gatherer│  │ investigator │  │ implementor  │        │
  │   │   (sonnet)     │  │   (opus)     │  │   (opus)     │        │
  │   │  read-only     │  │  read-only   │  │  writes code │        │
  │   └────────────────┘  └──────────────┘  └──────────────┘        │
  │                                                                  │
  └──────────────────────────────────────────────────────────────────┘
```

| Agent              | Role                                                                                |
|--------------------|-------------------------------------------------------------------------------------|
| `context-gatherer` | Phase-1 brief — SPEC.md + CLAUDE.md + recent activity + focus findings. Read-only. |
| `investigator`     | Answer one narrow question → grounded findings + proposed decision. Read-only.      |
| `implementor`      | Scoped file edits per an approved plan. Writes code; no git mutations.              |

**Conventions shared by all three:**
- No nested agent dispatch (agents never spawn sub-agents — orchestration stays at the skill).
- No git state mutation (only `implementor` writes files; none commit/push/checkout).
- Output cites by file path + symbol name, not line numbers (which drift).
- "Never fabricate" — missing data is reported in output, never papered over.

**Discovery caveat:** custom agents load at Claude Code **session start**. Adding or editing a file under `.claude/agents/` does NOT hot-reload. If `Agent(subagent_type: "X")` returns "not found", restart the session.

(Skills are different — they hot-load. Edit a SKILL.md and the next `/<name>` invocation picks it up.)

---

## External integrations

Most hackathon harnesses keep this simple — only one integration channel is wired by default:

| System    | How Claude reaches it          | Skills that use it                       |
|-----------|--------------------------------|------------------------------------------|
| GitHub    | `gh` CLI (`gh pr`, `gh api`)   | `/pr-feedback`, optional commit prompts  |

**No Jira, no Confluence.** Hackathon teams typically don't run those. If your team uses something else (Linear, a Slack channel, a Discord thread), you can add a `/<skill>` that integrates — see `/skill-create`.

**Per-action gates apply.** Posting a comment, creating a PR, or commenting on an issue is always behind an `AskUserQuestion` — Claude drafts, you approve.

---

## Iterating on the harness mid-hackathon

If you realize during the hackathon that you want a new automation:

```
/skill-create <name>           # interview → scaffold → iterate → done
                               # hot-loads; no restart needed

/agent-create <name>           # interview → scaffold → iterate → done
                               # requires session restart
```

Skills land in `.claude/skills/<name>/SKILL.md`. Agents land in `.claude/agents/<name>.md`. No source-of-truth/install split — the file IS the source of truth, and the dev's local copy IS the install.

---

## Things to NOT do

- ❌ **Edit code in chat without invoking a skill.** Even for tiny changes — the implementor agent gives you a clean audit trail and a deployable-state check.
- ❌ **Let SPEC.md drift.** If you change scope, update the spec before the next `/ship-it`. The spec is what every skill reads.
- ❌ **Push without explicit confirmation.** No skill in this harness pushes. Phase-6 commit prompts always print the push command for *you* to run.
- ❌ **Skip the deployable-state check.** Every increment must leave the project demoable. If you break it, you can't ship.
- ❌ **Forget sponsor requirements.** Hackathon prizes depend on sponsor integrations. SPEC.md captures these — the implementor checks them per increment.

---

## When stuck

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                      │
  │   1.  Re-read SPEC.md            ← canonical project context         │
  │   2.  Re-read the relevant CLAUDE.md         ← rules + commands      │
  │   3.  Check `git log --oneline -10`         ← what just shipped      │
  │   4.  Run /onboarding                       ← this walkthrough       │
  │   5.  If a skill is misbehaving, edit SKILL.md (hot-loads)           │
  │                                                                      │
  └──────────────────────────────────────────────────────────────────────┘
```

> **Rule of thumb:** every skill is plan-first. If `/<some-skill>` ever does something you didn't expect, that's a bug — fix the skill (or open an issue against the harness repo). The contract is: *Claude plans, you approve, Claude acts.*

Ship the demo. Document the debt.
