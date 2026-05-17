// Public sign-in / landing page.
//
// Announcement-ready: hero, 3-step "how it works", "what you'll need"
// callout, sign-in CTA, footer with GitHub link + version. Uses the
// paper-base palette + the existing Space Grotesk / Inter font stack.
//
// After successful sign-in, NextAuth redirects to ``callbackUrl`` which
// defaults to /onboarding.

import Link from "next/link";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { LoginButton } from "./login-button";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; stale?: string }>;
}) {
  const session = await auth();
  const params = await searchParams;
  // `?stale=1` arrives via the 401 fallback when a server component
  // hits the backend with an expired / refresh-failed id_token. In that
  // case keep the user on /login so they can hit "Continue with Google"
  // for a fresh grant — otherwise the auto-redirect-when-signed-in
  // loops back to /onboarding → /login → ...
  const isStale = params.stale === "1";
  if (session && !isStale) {
    redirect(params.next || "/onboarding");
  }
  const callbackUrl = params.next || "/onboarding";

  return (
    <main className="min-h-screen bg-paper text-ink flex flex-col">
      {/* Hero */}
      <section className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="max-w-3xl w-full flex flex-col items-center text-center gap-8">
          {isStale ? (
            <div
              role="status"
              aria-live="polite"
              className="w-full max-w-xl rounded-2xl border border-orange/40 bg-paper-2 px-5 py-4 text-sm text-ink text-left"
            >
              <div className="font-medium mb-1">Session expired</div>
              <p className="text-ink-2 leading-relaxed">
                Your session expired — please sign in again to keep your
                data in sync.
              </p>
            </div>
          ) : (
            <span className="text-xs uppercase tracking-[0.18em] text-ink-3 font-medium">
              v0.1.0 · multi-tenant · agentic deal hunter
            </span>
          )}

          <div className="flex flex-col gap-4">
            <h1
              className="font-display text-ink"
              style={{ fontSize: "var(--text-display-hero)", lineHeight: 1 }}
            >
              Goti
            </h1>
            <p
              className="text-ink-2 max-w-xl mx-auto"
              style={{ fontSize: "var(--text-subhead)", lineHeight: 1.45 }}
            >
              Your agent that negotiates parallel deals on Facebook
              Marketplace, Nextdoor, OfferUp, and Craigslist — with you
              approving every send.
            </p>
          </div>

          <div className="w-full max-w-sm flex flex-col gap-3 pt-4">
            <LoginButton callbackUrl={callbackUrl} />
            <p className="text-xs text-ink-3">
              We use Google sign-in to keep your account safe. Goti never
              sees your password.
            </p>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="px-6 pb-12">
        <div className="max-w-4xl mx-auto">
          <h2
            className="text-ink mb-6 text-center font-display"
            style={{ fontSize: "var(--text-display-2)" }}
          >
            How it works
          </h2>
          <ol className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Step
              n={1}
              title="Type your goal"
              body="Plain English: 'standing desk under $250 in SF, no IKEA.' Goti asks a budget clarifier."
            />
            <Step
              n={2}
              title="Goti hunts in parallel"
              body="Discovers listings across 4 marketplaces, opens negotiations on the ones you pick."
            />
            <Step
              n={3}
              title="You approve every send"
              body="Every outbound message + counter is gated by an approval card. You stay in control."
            />
          </ol>
        </div>
      </section>

      {/* What you'll need */}
      <section className="px-6 pb-16">
        <div className="max-w-2xl mx-auto rounded-3xl bg-paper-2 border border-ink-3/10 px-6 py-5">
          <h3 className="text-ink font-medium mb-2" style={{ fontSize: "var(--text-headline)" }}>
            What you&rsquo;ll need
          </h3>
          <ul className="text-ink-2 space-y-1.5 text-sm">
            <li>· A Google account (for sign-in).</li>
            <li>
              · An active Facebook Marketplace and/or Nextdoor login (Goti
              opens a remote browser tab so you can sign in once; cookies
              persist there for messaging).
            </li>
            <li>· About 90 seconds for onboarding.</li>
          </ul>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-ink-3/10 px-6 py-5">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-ink-3">
          <span>© 2026 Goti · v0.1.0</span>
          <div className="flex gap-4">
            <Link
              href="https://github.com/neelaychakravarthy/goti"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-ink"
            >
              GitHub
            </Link>
            <Link
              href="https://github.com/neelaychakravarthy/goti#how-it-works"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-ink"
            >
              How it works
            </Link>
          </div>
        </div>
      </footer>
    </main>
  );
}

interface StepProps {
  n: number;
  title: string;
  body: string;
}

function Step({ n, title, body }: StepProps) {
  return (
    <li className="rounded-2xl bg-paper-2 border border-ink-3/10 px-5 py-5 flex flex-col gap-2 text-left">
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-ink text-paper text-xs font-medium">
        {n}
      </span>
      <h3 className="text-ink font-medium" style={{ fontSize: "var(--text-headline)" }}>
        {title}
      </h3>
      <p className="text-ink-2 text-sm leading-relaxed">{body}</p>
    </li>
  );
}
