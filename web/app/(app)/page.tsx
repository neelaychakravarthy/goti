// Root `/` — the chat home.
//
// Behaviour:
//
// - Onboarding incomplete → redirect to /onboarding.
// - User has at least one non-terminal hunt → redirect to /c/<most-recent-id>.
// - Else → render the "new hunt" empty state (centered composer with the
//   "What are you trying to buy used?" prompt).
//
// Submitting the composer creates a hunt + navigates to /c/<new-hunt-id>.

import { redirect } from "next/navigation";

import { NewHuntComposer } from "@/components/chat/new-hunt-composer";
import { getActiveHunt, getMe } from "@/lib/api";

export default async function RootChatHome() {
  // Onboarding check — if the user hasn't finished, send them through it
  // first. Backend-unreachable defaults to "show the composer anyway".
  try {
    const me = await getMe();
    if (!me.onboarding_completed) {
      redirect("/onboarding");
    }
  } catch (err) {
    // Read ``status`` structurally rather than via ``instanceof ApiError``
    // — Next.js can duplicate class identities across bundle chunks, so
    // the instanceof check is unreliable in production builds. A backend
    // 401 should always force re-auth, not silently fall through to the
    // composer.
    const status =
      typeof (err as { status?: unknown })?.status === "number"
        ? (err as { status: number }).status
        : null;
    if (status === 401 || status === 403) {
      redirect("/login?stale=1");
    }
    // Backend unreachable — let the user see the composer; it'll surface
    // the error on submit.
  }

  // Active-hunt jump — if there's a non-terminal hunt, the user almost
  // certainly wants to continue it rather than start a new one. The
  // sidebar still shows "+ New hunt" if they actually wanted to start
  // fresh.
  try {
    const active = await getActiveHunt();
    if (active && active.id) {
      redirect(`/c/${encodeURIComponent(active.id)}`);
    }
  } catch {
    // Non-fatal.
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col items-center justify-center px-6 py-10 overflow-y-auto">
      <div className="w-full max-w-[720px] flex flex-col items-center gap-6">
        <div className="flex flex-col gap-3 text-center">
          <span className="text-micro uppercase tracking-[0.18em] text-ink-3 font-medium">
            Buyer agent for used marketplaces
          </span>
          <h1
            className="font-display font-bold text-ink leading-[1.04] tracking-[-0.02em]"
            style={{ fontSize: "clamp(32px, 5vw, 44px)" }}
          >
            What are you trying to buy used?
          </h1>
          <p className="text-body text-ink-2 max-w-[560px] mx-auto">
            Tell Goti what you want. It searches marketplaces, compares
            sellers, and drafts messages for your approval before anything
            sends.
          </p>
        </div>
        <NewHuntComposer />
      </div>
    </div>
  );
}
