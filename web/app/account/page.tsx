// /account — user account management surface.
//
// Server component: gates on session + fetches the enriched
// `/api/me` profile so the page can render synchronously without a
// client-side loading flash. Hands off to the interactive
// AccountView client component for all stateful bits (delete-account
// modal, unlink buttons, location edit).
//
// If the user isn't signed in we bounce to /login; if the backend
// 401s we treat that the same way (the session is stale).

import { redirect } from "next/navigation";

import { ErrorMessage } from "@/components/ui/error-message";
import { UserMenu } from "@/components/topnav/user-menu";
import { auth } from "@/auth";
import { getMe } from "@/lib/api";

import { AccountView } from "./account-view";

export default async function AccountPage() {
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
    // Read ``status`` structurally rather than via ``instanceof ApiError``
    // — see the equivalent comment in ``app/onboarding/page.tsx`` for why
    // the instanceof check is flaky in production bundles.
    const status =
      typeof (err as { status?: unknown })?.status === "number"
        ? ((err as { status: number }).status)
        : null;
    const path =
      typeof (err as { path?: unknown })?.path === "string"
        ? (err as { path: string }).path
        : "GET /api/me";
    if (status === 401 || status === 403) {
      // Stale id_token — break the /login ↔ /onboarding loop with
      // ?stale=1 so the user can re-authenticate.
      redirect("/login?stale=1");
    }
    backendUnavailable = true;
    // ``err.message`` carries the backend's ``detail`` field when the
    // response had one — e.g. ``GET /api/me failed: 500 — TypeError:
    // 'NoneType' object has no attribute 'isoformat'``. Fall back to
    // path + status when the body wasn't JSON.
    const msg = err instanceof Error ? err.message : String(err);
    backendError = msg && msg.length > 0 ? msg : `${path} → HTTP ${status ?? "?"}`;
    me = null;
  }

  return (
    <main className="min-h-screen bg-paper text-ink py-10 px-4">
      <div className="mx-auto w-full max-w-2xl flex justify-end pb-4">
        <UserMenu />
      </div>
      <div className="mx-auto w-full max-w-2xl">
        {backendUnavailable || !me ? (
          <div className="rounded-3xl bg-white shadow-paper px-8 py-10">
            <ErrorMessage
              title="Backend unavailable"
              body={`Goti couldn't load your account. Refresh once the API is reachable.${
                backendError ? ` (${backendError})` : ""
              }`}
            />
          </div>
        ) : (
          <AccountView user={me} />
        )}
      </div>
    </main>
  );
}
