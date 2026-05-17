// Module augmentation for next-auth (Auth.js v5) — extends the JWT
// shape so `token.id_token`, `token.refresh_token`, `token.expires_at`,
// and `token.error` are properly typed in the `jwt` callback. Mirrors
// the fields the Google provider stashes on first sign-in + that the
// refresh-token rotation in `web/auth.ts` reads/writes.

import "next-auth/jwt";

declare module "next-auth/jwt" {
  interface JWT {
    id_token?: string;
    refresh_token?: string;
    /** Seconds since epoch — Google's `expires_at` convention. */
    expires_at?: number;
    google_sub?: string;
    /** Set to `"RefreshAccessTokenError"` when a refresh attempt fails. */
    error?: string;
  }
}
