// Next.js 16 "proxy" (formerly "middleware") — runs server-side before
// each request. Gates protected routes by checking the NextAuth session
// cookie; unauthenticated requests get bounced to /login.
//
// Routes that DON'T require auth:
//   /login                — public sign-in
//   /api/auth/*           — NextAuth internal handlers (signin / callback / signout / session)
//   /favicon.ico, /_next/*— static assets

import NextAuth from "next-auth";
import { NextResponse } from "next/server";

const { auth: authProxy } = NextAuth({
  // Minimal NextAuth config for the proxy edge runtime — just enough to
  // read the session cookie. The full Google provider config lives in
  // /auth.ts (used by route handlers + server components).
  providers: [],
});

const PUBLIC_PATHS = ["/login"];
const PUBLIC_PREFIXES = ["/api/auth"];

export default authProxy((req) => {
  const { pathname } = req.nextUrl;

  // Allow public paths through.
  if (PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.next();
  }
  if (PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Authed: continue.
  if (req.auth) {
    // Redirect "/" to /onboarding (or /start once complete) — the server
    // component at "/" handles the smart redirect, so just let it through.
    return NextResponse.next();
  }

  // Unauthed: bounce to /login, preserving the original target in `?next=`.
  const loginUrl = new URL("/login", req.nextUrl.origin);
  if (pathname !== "/") {
    loginUrl.searchParams.set("next", pathname);
  }
  return NextResponse.redirect(loginUrl);
});

export const config = {
  // Run the proxy on everything except static assets + next-internals.
  // The matcher uses regex-style alternation; this exclude pattern is
  // the canonical Next.js 16 shape.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.png$).*)"],
};
