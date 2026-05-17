// Catch-all NextAuth route handlers: /api/auth/signin, /api/auth/callback/google,
// /api/auth/signout, /api/auth/session, etc.
//
// In Auth.js v5 the configured NextAuth() call returns a `handlers`
// object with GET + POST keys; we re-export them here so Next.js sees
// the route handler shape.

import { handlers } from "@/auth";

export const { GET, POST } = handlers;
