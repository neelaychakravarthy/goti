# Deploying Goti's frontend to Vercel

This covers ONLY the Next.js `web/` frontend. The FastAPI `api/` backend
+ Postgres live on Zeabur — see [`ZEABUR.md`](./ZEABUR.md).

## TL;DR — Dashboard deploy

1. **Push the repo to GitHub.** Make sure the `web/` directory is
   committed — Vercel will only see what's in the remote.

2. **Create a Vercel project.** From the Vercel dashboard:
   *Add New* → *Project* → import this repo.

3. **Set the root directory.** This is the most-bitten step:
   - Open *Settings* → *General*.
   - Set **Root Directory** to `web` (not the repo root).
   - Confirm **Framework Preset** is `Next.js`. If Vercel shows
     "Other" / nothing, set it manually to **Next.js**. **Forgetting
     this step is the documented cause of a 404 on every route**
     when the project first deploys.

4. **Set the env vars.** *Settings* → *Environment Variables*. Add
   to **Production** + **Preview** + **Development**:

   | Variable | Value |
   |---|---|
   | `NEXTAUTH_SECRET` | Generate with `openssl rand -base64 32` |
   | `NEXTAUTH_URL` | The production Vercel URL (e.g. `https://goti.vercel.app`) |
   | `NEXT_PUBLIC_API_BASE_URL` | The Zeabur backend URL (e.g. `https://goti-api.zeabur.app`) |
   | `GOOGLE_OAUTH_CLIENT_ID` | Google Cloud Console → OAuth 2.0 Client → Web → Client ID |
   | `GOOGLE_OAUTH_CLIENT_SECRET` | Same screen → Client secret |
   | `NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID` | Same value as `GOOGLE_OAUTH_CLIENT_ID` (exposed to the client for NextAuth) |

   Make sure `GOOGLE_OAUTH_CLIENT_ID` matches what the Zeabur backend
   is configured with — the backend verifies the Google ID token against
   that audience, and a mismatch produces a 401 on every `/api/*` call.

5. **Configure Google Cloud Console.** Open the OAuth 2.0 Web Client
   used above:
   - **Authorized JavaScript origins:**
     - `http://localhost:3000` (dev)
     - `https://<vercel-prod-domain>` (e.g. `https://goti.vercel.app`)
     - Any preview-deployment domain pattern you want to allow
   - **Authorized redirect URIs:**
     - `http://localhost:3000/api/auth/callback/google` (dev)
     - `https://<vercel-prod-domain>/api/auth/callback/google`

6. **Trigger the first deploy.** Push to `main`, or click *Deploy*
   in the Vercel dashboard. The build runs `npm run build` from
   `web/`; first build takes ~2 minutes.

7. **Custom domain (optional).** *Settings* → *Domains* → add your
   domain. After DNS propagates, update:
   - `NEXTAUTH_URL` to the custom domain
   - Google Cloud Console authorized origins + redirect URIs
   - `GOTI_ALLOWED_ORIGINS` in the Zeabur backend so CORS lets the new
     origin through

## Connection test

After the deploy lands:

1. Open the Vercel URL → you should see the `/login` page.
2. Click *Continue with Google* → complete the Google flow.
3. You should land on `/onboarding`. If it errors with "Backend
   unavailable" or you see 401s in the network tab, the Zeabur
   backend isn't reachable from the browser — check
   `NEXT_PUBLIC_API_BASE_URL` + the backend's `GOTI_ALLOWED_ORIGINS`.
4. Open DevTools → Network → look for `GET /api/me` returning 200
   with your user shape. This confirms:
   - Vercel ↔ Zeabur reachability
   - Google ID token verification on the backend
   - The user upsert worked

If `/api/me` returns 401: check `GOOGLE_OAUTH_CLIENT_ID` matches on
both deploys.

## Troubleshooting

- **Every route 404s.** Root Directory wasn't set to `web`, or
  Framework Preset isn't `Next.js`. Fix in Settings → General and
  redeploy.
- **`/login` button doesn't redirect anywhere.** Google Cloud Console
  redirect URI doesn't match `https://<vercel-domain>/api/auth/callback/google`.
- **401s on `/api/*` after sign-in.** `GOOGLE_OAUTH_CLIENT_ID` on
  Vercel ≠ on Zeabur. They must be equal.
- **CORS errors in the console.** `GOTI_ALLOWED_ORIGINS` on Zeabur
  doesn't include the Vercel domain. Comma-separated; no trailing
  slashes.
