// Onboarding checklist — the post-sign-in landing page.
//
// Shows a 3-step checklist:
//  1. Signed in as <name>  (auto-complete from Google profile)
//  2. Link your marketplaces (provisions a Browserbase Context + opens
//     a Live View tab; user signs into FB Marketplace + Nextdoor, then
//     clicks "I'm done logging in" to call /finish).
//  3. (Optional) Set default location
//
// "Start your first hunt" CTA becomes available when marketplaces are
// linked. Clicking it POSTs /api/me/onboarding/complete then routes
// to /start.
//
// If the user has already finished onboarding, redirect straight to
// /start so we don't re-prompt them every session.

import { redirect } from "next/navigation";

import { ErrorMessage } from "@/components/ui/error-message";
import { UserMenu } from "@/components/topnav/user-menu";
import { auth } from "@/auth";
import { getMe } from "@/lib/api";
import { OnboardingChecklist } from "./checklist";

export default async function OnboardingPage() {
  const session = await auth();
  if (!session) {
    redirect("/login");
  }
  let me;
  let backendUnavailable = false;
  let backendError: string | null = null;
  try {
    me = await getMe();
  } catch (err) {
    // Read ``status`` structurally rather than via ``instanceof ApiError``.
    // Next.js can duplicate class identities across bundle chunks (server
    // vs RSC vs route handler), which makes ``instanceof`` flaky in
    // production while it works fine in dev — a 401 from the backend
    // would silently fall through to the "Backend unavailable" branch
    // instead of redirecting to ``/login?stale=1``.
    const status =
      typeof (err as { status?: unknown })?.status === "number"
        ? ((err as { status: number }).status)
        : null;
    const path =
      typeof (err as { path?: unknown })?.path === "string"
        ? (err as { path: string }).path
        : "GET /api/me";
    if (status === 401 || status === 403) {
      // Backend rejected the id_token — the NextAuth session cookie is
      // still valid (so a plain /login redirect would bounce right back
      // here). Use ?stale=1 to break the loop and force a fresh grant.
      redirect("/login?stale=1");
    }
    // 5xx / network error — render an error state so the user can sign out / retry.
    backendUnavailable = true;
    // ``err.message`` now carries the backend's ``detail`` field when
    // the response had one — see ``lib/api.ts`` getJSON. Fall back to
    // path + status when the body wasn't JSON.
    const msg = err instanceof Error ? err.message : String(err);
    backendError = msg && msg.length > 0 ? msg : `${path} → HTTP ${status ?? "?"}`;
    me = null;
  }
  if (me?.onboarding_completed) {
    redirect("/");
  }
  return (
    <main className="min-h-screen flex flex-col items-center bg-paper text-ink py-6 px-4">
      <div className="w-full max-w-xl flex justify-end pb-4">
        <UserMenu />
      </div>
      <div className="max-w-xl w-full rounded-3xl bg-white shadow-paper px-8 py-10 mt-6">
        <h1 className="text-3xl font-display mb-2">Welcome to Goti</h1>
        <p className="text-graphite mb-8">
          A few quick setup steps so we can negotiate on your behalf.
        </p>
        {backendUnavailable ? (
          <ErrorMessage
            title="Backend unavailable"
            body={`Goti's backend isn't reachable right now. Refresh once it's back up.${
              backendError ? ` (${backendError})` : ""
            }`}
          />
        ) : (
          <OnboardingChecklist user={me} />
        )}
      </div>
    </main>
  );
}
