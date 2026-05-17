// NextAuth.js v5 (Auth.js) configuration — Google OAuth sign-in.
//
// The frontend's sole identity provider is Google. The Google ID token
// is captured in the JWT callback so server components / route handlers
// can read it from the session and forward it to the backend as
// `Authorization: Bearer <id_token>`. The backend verifies the same
// token against Google's JWKS using the shared GOOGLE_OAUTH_CLIENT_ID
// as the audience.
//
// Google ID tokens expire after 1h, but the NextAuth session cookie is
// long-lived (30d default). To avoid the backend 401-ing once the
// stashed id_token goes stale, we request `access_type=offline` so we
// receive a `refresh_token` on first sign-in and rotate the id_token
// from Google's token endpoint when it's about to expire.
//
// Env vars (see .env.example):
//   - GOOGLE_OAUTH_CLIENT_ID — used by both ends; same value
//   - GOOGLE_OAUTH_CLIENT_SECRET — frontend only
//   - NEXTAUTH_SECRET (or AUTH_SECRET) — encrypts the NextAuth session cookie
//
// Pages routes:
//   /login   — public sign-in page (renders signIn("google"))
//   /onboarding — post-sign-in checklist; redirects authed users with
//                 onboarding_completed=true straight to /start.

import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

export const { handlers, auth, signIn, signOut } = NextAuth({
  // Encrypts the NextAuth session cookie. Auth.js v5 reads `AUTH_SECRET`
  // by default; accept the older `NEXTAUTH_SECRET` name too so deploys
  // that use either env-var convention work without code changes.
  secret: process.env.AUTH_SECRET ?? process.env.NEXTAUTH_SECRET,
  // /login is the public entry; everything else demands a session.
  pages: {
    signIn: "/login",
  },
  providers: [
    Google({
      clientId: process.env.GOOGLE_OAUTH_CLIENT_ID,
      clientSecret: process.env.GOOGLE_OAUTH_CLIENT_SECRET,
      authorization: {
        params: {
          // Request offline access so Google issues a refresh_token on
          // the first grant. `prompt=consent` forces the consent screen
          // even for repeat users so the refresh_token is always
          // returned (Google only sends it the first time consent is
          // given otherwise).
          access_type: "offline",
          prompt: "consent",
        },
      },
    }),
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      // First sign-in: capture id_token + refresh_token + expiry.
      if (account) {
        token.id_token = account.id_token;
        token.refresh_token = account.refresh_token;
        // Google returns `expires_at` as seconds since epoch.
        token.expires_at = account.expires_at;
        if (account.providerAccountId) {
          token.google_sub = account.providerAccountId;
        }
        if (profile?.picture) {
          token.picture = profile.picture;
        }
        return token;
      }

      // Subsequent calls: refresh proactively a minute before expiry.
      const now = Math.floor(Date.now() / 1000);
      const expiresAt = token.expires_at;
      if (typeof expiresAt === "number" && now < expiresAt - 60) {
        return token; // Still valid.
      }

      // No refresh_token captured — user signed in before the offline-
      // access change, or Google didn't issue one. Mark the session
      // expired so the frontend can fall back to `?stale=1` and force a
      // fresh sign-in.
      if (!token.refresh_token) {
        token.error = "RefreshAccessTokenError";
        return token;
      }

      try {
        const response = await fetch("https://oauth2.googleapis.com/token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            client_id: process.env.GOOGLE_OAUTH_CLIENT_ID ?? "",
            client_secret: process.env.GOOGLE_OAUTH_CLIENT_SECRET ?? "",
            grant_type: "refresh_token",
            refresh_token: token.refresh_token,
          }),
        });
        const refreshed = (await response.json()) as {
          id_token?: string;
          access_token?: string;
          refresh_token?: string;
          expires_in?: number;
          error?: string;
          error_description?: string;
        };
        if (!response.ok) {
          throw refreshed;
        }
        if (refreshed.id_token) {
          token.id_token = refreshed.id_token;
        }
        token.expires_at =
          Math.floor(Date.now() / 1000) + (refreshed.expires_in ?? 3600);
        // Google may or may not return a new refresh_token; keep the
        // existing one if Google omits it from the refresh response.
        if (refreshed.refresh_token) {
          token.refresh_token = refreshed.refresh_token;
        }
        delete token.error;
      } catch (err) {
        // Refresh failed — could be a revoked grant, network blip, or
        // a misconfigured client. Stamp the session with an error flag
        // so the frontend's 401 path triggers `?stale=1` and the user
        // re-authenticates cleanly.
        console.error("Google id_token refresh failed:", err);
        token.error = "RefreshAccessTokenError";
      }
      return token;
    },
    async session({ session, token }) {
      // Expose the id_token + google_sub on the session object. The
      // id_token is the bearer credential the backend accepts.
      if (token?.id_token) {
        (session as { id_token?: string }).id_token = token.id_token;
      }
      if (token?.google_sub) {
        (session as { google_sub?: string }).google_sub = token.google_sub;
      }
      if (token?.error) {
        (session as { error?: string }).error = token.error;
      }
      if (token?.picture && session.user) {
        session.user.image = token.picture as string;
      }
      return session;
    },
  },
});
