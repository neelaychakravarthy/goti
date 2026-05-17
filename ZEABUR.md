# Deploying Goti's backend to Zeabur

This covers ONLY the FastAPI `api/` service + the Postgres add-on.
The Next.js `web/` frontend lives on Vercel — see the Vercel section
at the bottom for the cross-link.

`zeabur.toml` at the repo root captures the deploy config in
declarative form. If Zeabur's auto-import doesn't pick it up, the
dashboard steps below produce the same shape.

## TL;DR — Dashboard deploy

1. **Push the repo to GitHub.** Make sure `api/Dockerfile`,
   `api/requirements.txt`, and the `api/` source tree are all
   committed. The Dockerfile is rooted at the repo root: it does
   `COPY api /app/api` (the repo root must be the build context).

2. **Create a Zeabur project.** From the Zeabur dashboard:
   *New Project* → name it `goti`.

3. **Add the Postgres add-on.** Inside the project, click
   *Add Service* → *Prebuilt* → *PostgreSQL*. Zeabur provisions a
   Postgres instance and exposes the connection string as the
   `POSTGRES_URI` env var (along with sibling `POSTGRES_HOST`,
   `POSTGRES_PORT`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`,
   `POSTGRES_DATABASE`) — injected automatically into any linked
   service in the same project. The backend reads `POSTGRES_URI`
   directly.

4. **Add the API service.** Inside the same project,
   *Add Service* → *Git Repository* → connect this repo (or the
   GitHub org-mirror of it). Zeabur auto-detects the Dockerfile;
   set:
   - **Build context:** `.` (repo root)
   - **Dockerfile path:** `api/Dockerfile`
   - **Port:** `8000` (matches `EXPOSE 8000` in the Dockerfile)
   - **Health check path:** `/docs` (FastAPI's auto-generated docs;
     200 if app boots, no DB hit required)

5. **Set the env vars.** In the API service's *Variables* tab,
   add these (paste values from `.env` / 1Password):

   | Variable | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | (Anthropic API key from https://console.anthropic.com/) |
   | `EVEROS_API_KEY` | (EverOS / Evermind API key) |
   | `BROWSERBASE_API_KEY` | (Browserbase API key from https://browserbase.com/dashboard — single key serves all Goti users via Contexts API) |
   | `BROWSERBASE_PROJECT_ID` | (Browserbase project id from the same dashboard) |
   | `AF_CONTROL_PLANE_URL` | `http://localhost:8000` — FastAPI IS the AgentField control plane (the bridge router in `api/routes/agent_bridge.py` mounts the `/api/v1/...` endpoints AgentField calls). Reasoners running alongside FastAPI in the same container point here via loopback. Override only if FastAPI binds to a non-default port. |
   | `CLAUDE_MODEL_ID` | `claude-haiku-4-5-20251001` (default — cheap + fast). Set to `claude-sonnet-4-6` for higher-quality negotiation drafts at higher cost. |
   | `GOTI_DEMO_USER_ID` | `demo_user` |
   | `GOTI_ALLOWED_ORIGINS` | Comma-separated list of allowed CORS origins. Set to your Vercel deployment URL in production (e.g. `https://goti.vercel.app`). Empty default falls back to `http://localhost:3000` + `https://*.vercel.app` for dev. |
   | `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client_id — must match the value the Vercel frontend uses (NextAuth Google provider). |

   `POSTGRES_URI` is auto-populated by the Postgres add-on once the
   add-on is **linked** to the API service — don't add it manually.
   If `/api/me` 500s with `gaierror: Name or service not known`,
   it means the link isn't there: open the API service → Variables,
   check the *Auto-generated* section for `POSTGRES_URI`. If missing,
   link the Postgres add-on to the service (or restart the API
   service after linking) and re-deploy.

6. **Deploy.** Click *Deploy* on the API service. Zeabur:
   - Builds the image from `api/Dockerfile`.
   - Boots the container, which runs `api/main.py`'s lifespan
     hook → applies Alembic migrations automatically against the
     fresh Postgres → starts uvicorn on `:8000`.
   - Issues a public URL (e.g. `https://goti-api-xxx.zeabur.app`).

7. **Verify.** Hit `https://<zeabur-api-domain>/docs` → FastAPI's
   Swagger UI loads, listing all 32 routes. Hit
   `https://<zeabur-api-domain>/health` → `{"status": "ok"}`.

## Re-deploys

Push to `main` → Zeabur auto-rebuilds + redeploys (if the repo
connection is enabled). Alembic migrations re-run on each boot via
the `lifespan` hook, so schema changes ship with the same push.

## Frontend cross-link (Vercel)

The Vercel-side `web/` deploy needs these env vars under the
`web/` project's *Environment Variables* → *Production*:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://<zeabur-api-domain>` — the URL of this Zeabur backend |
| `NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client_id (same value as backend's `GOOGLE_OAUTH_CLIENT_ID`) |
| `GOOGLE_OAUTH_CLIENT_ID` | Same client_id; NextAuth reads this server-side |
| `GOOGLE_OAUTH_CLIENT_SECRET` | OAuth client secret from Google Cloud Console |
| `NEXTAUTH_SECRET` | `openssl rand -base64 32` — encrypts NextAuth session cookies |
| `NEXTAUTH_URL` | The Vercel production URL, e.g. `https://goti.vercel.app` |

After deploying, ensure the Zeabur backend's `GOTI_ALLOWED_ORIGINS`
env var includes the Vercel deployment URL, otherwise the browser's
CORS preflight will reject every fetch.

## Deploy sanity check

- Backend reachable at a public Zeabur URL (`https://<zeabur-api-domain>`).
- Combined with the Vercel frontend, the full app is reachable at
  `https://<vercel-app>.vercel.app`.
