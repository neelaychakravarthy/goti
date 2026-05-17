"use client";

// Thin wrapper exposing the NextAuth SessionProvider so client components
// can call useSession() / signIn() / signOut(). Keeps the cookie-based
// session in sync across the tree.
//
// We explicitly disable both poll-based refetch (`refetchInterval=0`) and
// window-focus refetch. The Goti app reads the session via the shared
// client-side token cache (`web/lib/session-token.ts`); NextAuth's
// internal refetches would just compete with that cache and risk a
// `/api/auth/session` storm when many components mount at once.

import { SessionProvider } from "next-auth/react";

export function AuthSessionProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <SessionProvider
      refetchInterval={0}
      refetchOnWindowFocus={false}
      refetchWhenOffline={false}
    >
      {children}
    </SessionProvider>
  );
}
