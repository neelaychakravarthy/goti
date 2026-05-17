// Shared client-side cache for the Google ID token captured by NextAuth.
//
// Every backend call (api-client.ts, notifications-context.tsx, the
// onboarding checklist) forwards `Authorization: Bearer <id_token>`.
// Without this cache, each wrapper would hit `/api/auth/session` on
// every invocation — a busy page (polling poll-based `getHunt` every
// 1.5s on the search page, while the sidebar's `getHunts` boots, while
// the notifications bootstrap fetches, while the approval-decision POST
// fires, etc.) easily produces dozens of session calls per second.
//
// Cache shape:
//   - One in-flight promise is deduped (so concurrent callers piggyback).
//   - Resolved tokens are cached for ``SESSION_TOKEN_TTL_MS`` (default 5
//     minutes — well inside Google's 1-hour ID-token expiry but short
//     enough that a fresh sign-in's token is picked up on the next call).
//   - The cache is invalidated by ``clearCachedIdToken()`` — used after
//     a 401 from the backend so the next request fetches a fresh token.

const SESSION_TOKEN_TTL_MS = 5 * 60 * 1000;

interface CacheEntry {
  token: string | null;
  fetchedAt: number;
}

let cached: CacheEntry | null = null;
let inflight: Promise<string | null> | null = null;

async function _fetchFromNextAuth(): Promise<string | null> {
  try {
    const r = await fetch("/api/auth/session", { cache: "no-store" });
    if (!r.ok) return null;
    const data = (await r.json()) as { id_token?: string } | null;
    return data?.id_token ?? null;
  } catch {
    return null;
  }
}

/**
 * Return the Google ID token from the NextAuth session. Short-lived
 * cache + in-flight dedupe — multiple concurrent / sequential calls
 * share a single ``/api/auth/session`` round-trip.
 */
export async function getCachedIdToken(): Promise<string | null> {
  const now = Date.now();
  if (cached && now - cached.fetchedAt < SESSION_TOKEN_TTL_MS) {
    return cached.token;
  }
  if (inflight) {
    return inflight;
  }
  inflight = (async () => {
    try {
      const token = await _fetchFromNextAuth();
      cached = { token, fetchedAt: Date.now() };
      return token;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/**
 * Invalidate the cached token. Call this after a 401/403 from the
 * backend (the token may have rotated) so the next call refetches.
 * Also call from sign-out flows.
 */
export function clearCachedIdToken(): void {
  cached = null;
  inflight = null;
}
