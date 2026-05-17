"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ActivityBell } from "@/components/topnav/activity-bell";
import { GotiMark } from "@/components/topnav/goti-mark";
import { UserMenu } from "@/components/topnav/user-menu";
import { HuntRow, type HuntStatus } from "@/components/sidebar/hunt-row";
import { InboxPanel } from "@/components/sidebar/inbox-panel";
import { getHunts } from "@/lib/api-client";
import { useNotifications } from "@/lib/notifications-context";
import { cn } from "@/lib/utils";
import type { HuntState } from "@/types";

// How often to refresh the hunts list in the background. Bumped on
// every notification-stream event (new listing, task done, deal close,
// etc.) AND on navigation changes — so pause/stop/resume/delete from
// the hunt control menu shows up here without a manual refresh.
const POLL_INTERVAL_MS = 5_000;

interface Hunt {
  /** Hunt UUID (matches `?hunt_id=` query param for active-state). */
  id: string;
  title: string;
  subline: string;
  status: HuntStatus;
  href: string;
}

/** Map a backend `HuntState.status` enum to the sidebar's status badge color. */
function statusForHuntState(state: HuntState): HuntStatus {
  switch (state.status) {
    case "awaiting_clarification":
    case "awaiting_picks":
      return "waiting";
    case "discovering":
      return "searching";
    case "negotiating":
      return "reply";
    case "paused":
      return "paused";
    case "closed":
      return "closed";
    case "error":
      return "error";
    default:
      return "searching";
  }
}

/** Human-readable badge text. Reserved for future render — not consumed yet
 * by HuntRow, which renders the dot only. */
function statusBadgeText(state: HuntState): string {
  switch (state.status) {
    case "awaiting_clarification":
      return "Awaiting answer";
    case "discovering":
      return "Searching";
    case "awaiting_picks":
      return "Picking";
    case "negotiating":
      return "Negotiating";
    case "paused":
      return "Paused";
    case "closed":
      return "Closed";
    case "error":
      return "Error";
    default:
      return state.status;
  }
}

function mapLiveHunt(state: HuntState): Hunt {
  const title = state.goal_text.length > 40
    ? `${state.goal_text.slice(0, 40)}…`
    : state.goal_text;
  return {
    id: state.id,
    title: title || "Untitled hunt",
    subline: statusBadgeText(state),
    status: statusForHuntState(state),
    // Chat-first control plane — each hunt is its own conversation
    // page at /c/<hunt_id> (ChatGPT-style URL).
    href: `/c/${encodeURIComponent(state.id)}`,
  };
}

interface HuntSidebarProps {
  className?: string;
}

/**
 * Left rail listing the user's product hunts. Visible at lg+ widths.
 *
 * Data source:
 *   - On mount, calls GET /api/hunts. Real hunts are the only source —
 *     no hardcoded fallback (legacy fixtures removed).
 *   - During the initial fetch, renders a 3-row skeleton.
 *   - When the fetch returns []: empty state ("No hunts yet — type a
 *     goal on /start").
 *   - When the fetch fails: same empty-state path so the demo flow keeps
 *     working even when the backend is down.
 *
 * Top: Goti mark + "New hunt" CTA. Body: hunt rows. Foot: Playbook link.
 */
export function HuntSidebar({ className }: HuntSidebarProps) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  // Hunt id can live in either `?hunt_id=` (legacy) or the path `/c/<id>`
  // (chat-first). Both resolve here so the active-row highlight works.
  const huntIdFromQuery = searchParams?.get("hunt_id") ?? null;
  const huntIdFromPath = pathname?.match(/^\/c\/([^/]+)/)?.[1] ?? null;
  const huntIdParam = huntIdFromQuery ?? huntIdFromPath ?? null;
  const router = useRouter();

  // null = not yet loaded; [] = loaded-and-empty; >0 = loaded-with-rows.
  const [liveHunts, setLiveHunts] = useState<HuntState[] | null>(null);
  const { notifications } = useNotifications();
  // ``notifCount`` as a dep means each new notification triggers a
  // refetch — covers new-listing / task-completed / hunt-closed events.
  const notifCount = notifications.length;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const rows = await getHunts();
        if (!cancelled) setLiveHunts(rows);
      } catch {
        if (!cancelled) {
          // Keep whatever we had on transient failure; only flip to []
          // on the very first load failure.
          setLiveHunts((prev) => (prev === null ? [] : prev));
        }
      }
    }
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // ``pathname`` triggers a refetch when the user navigates between
    // hunts (e.g., creates a new hunt + lands on /c/<new-id>); the
    // sidebar will then include the new row before the next poll tick.
  }, [pathname, notifCount]);

  const isLoading = liveHunts === null;
  const hunts: Hunt[] = liveHunts ? liveHunts.map(mapLiveHunt) : [];

  return (
    <aside
      className={cn(
        "hidden lg:flex w-[260px] shrink-0 sticky top-0 self-start h-screen flex-col bg-paper-2 border-r",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.08)" }}
      aria-label="Product hunts"
    >
      <div className="flex flex-col gap-3 px-4 pt-5 pb-4">
        <GotiMark />
        <InboxPanel />
        <button
          type="button"
          onClick={() => router.push("/")}
          className={cn(
            "w-full inline-flex items-center justify-center gap-1.5 rounded-2xl border bg-paper px-3 py-2",
            "text-caption font-medium text-ink hover:bg-paper-3 transition-colors"
          )}
          style={{ borderColor: "rgba(15,15,15,0.12)" }}
        >
          <span aria-hidden className="text-ink-2">+</span>
          <span>New hunt</span>
        </button>
      </div>

      <div
        className="mx-4 border-t"
        style={{ borderColor: "rgba(15,15,15,0.08)" }}
      />

      <div className="px-4 pt-4 pb-2">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
          Product hunts
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto" aria-label="Hunts">
        {isLoading ? (
          <ul aria-hidden className="flex flex-col gap-2 px-4 pt-1">
            {[0, 1, 2].map((i) => (
              <li
                key={i}
                className="h-10 rounded-lg bg-paper-3 animate-pulse"
              />
            ))}
          </ul>
        ) : hunts.length === 0 ? (
          <div className="px-4 pt-2 text-caption text-ink-3 leading-relaxed">
            No hunts yet — type a goal in the chat box.
          </div>
        ) : (
          <ul className="flex flex-col">
            {hunts.map((hunt, idx) => {
              const active = huntIdParam !== null && huntIdParam === hunt.id;
              return (
                <li
                  key={hunt.id}
                  className={cn(idx > 0 && "border-t")}
                  style={
                    idx > 0
                      ? { borderColor: "rgba(15,15,15,0.06)" }
                      : undefined
                  }
                >
                  <HuntRow
                    title={hunt.title}
                    subline={hunt.subline}
                    status={hunt.status}
                    active={active}
                    href={hunt.href}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      <div
        className="border-t px-3 py-2.5 flex items-center justify-between gap-2"
        style={{ borderColor: "rgba(15,15,15,0.08)" }}
      >
        <Link
          href="/playbook"
          className="text-micro uppercase tracking-[0.08em] text-ink-2 hover:text-ink font-semibold px-1"
        >
          Memory
        </Link>
        <div className="flex items-center gap-1">
          <ActivityBell />
          <UserMenu />
        </div>
      </div>
    </aside>
  );
}
