# Contributing to Goti

Thanks for your interest in Goti. This document covers the practical bits
of contributing — local setup, branch conventions, commit style, and PR
process.

## Local development

See the [README](./README.md) Quickstart. Minimum:

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY + GOOGLE_OAUTH_CLIENT_ID at minimum.
docker compose up --build
```

Frontend at `http://localhost:3000`, backend at `http://localhost:8000`.

Backend tests:

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -m "not live"
```

Frontend lint + typecheck:

```bash
cd web
npm install
npm run lint
npm run build
```

## Branch naming

We use short, descriptive branch names with a category prefix:

- `feat/<slug>` — new feature
- `fix/<slug>` — bug fix
- `chore/<slug>` — refactor, build, deps
- `docs/<slug>` — docs only

Example: `feat/lifecycle-resumption`, `fix/oauth-state-race`.

## Commit messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<optional body>

<optional footer>
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`.
Scopes (when useful): `api`, `web`, `deploy`, `repo`.

Examples from this repo's history:

- `feat(api): durable hunt lifecycle resumption via lifecycle_phase column`
- `fix(web): rate-limit OAuth init to 5/min`
- `chore(deploy): drop stale GOTI_DEMO_USER_ID from zeabur.toml`

## Pull request process

1. Fork or branch from `main`.
2. Make focused commits (one logical change per commit).
3. Run `pytest -m "not live"` (backend) + `npm run build` (frontend) before
   opening the PR.
4. Open a PR with the template (Summary + Test plan).
5. Keep the PR scope tight — drive-by refactors should be separate PRs.
6. Squash merge once approved.

## External integrations

This project ships with six external integrations (AgentField, Anthropic
Claude, EverOS, Browserbase + browser-use, Zeabur + Vercel). When
touching any of them, re-read the relevant code path before sending the
PR — these integrations are easy to break with a refactor.

## Code of conduct

Be excellent to each other. Disagree about technical details, not about
people. If something feels off, raise it directly with the maintainer
(see `SECURITY.md` for the contact).
