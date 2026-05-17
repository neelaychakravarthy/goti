"use client";

// Pinned strip showing the hunt's active per-listing negotiations.
// Each pill click opens the seller-conversation slideover for that
// job. Refreshes every 5s + on every notifications-stream event so
// freshly-started negotiations appear without a page reload.

import { useEffect, useMemo, useState } from "react";

import { getHuntListings, type HuntListingEntry } from "@/lib/api-client";
import { useNotifications } from "@/lib/notifications-context";
import { cn } from "@/lib/utils";

interface Props {
  huntId: string;
  onOpen: (jobId: string) => void;
  className?: string;
}

export function ActiveNegotiationsStrip({ huntId, onOpen, className }: Props) {
  const [listings, setListings] = useState<HuntListingEntry[]>([]);
  const { notifications } = useNotifications();
  const notifCount = notifications.length;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const ls = await getHuntListings(huntId);
        if (!cancelled) setListings(ls);
      } catch {
        /* keep prior listings on failure */
      }
    }
    load();
    const id = setInterval(load, 5_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [huntId, notifCount]);

  const activeJobs = useMemo(
    () =>
      listings.filter((l) => {
        if (!l.job_id) return false;
        const s = l.job_status ?? "";
        return s !== "closed" && s !== "cancelled";
      }),
    [listings]
  );

  if (activeJobs.length === 0) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-2 overflow-x-auto px-1 py-1 -mx-1",
        className
      )}
      role="list"
      aria-label="Active negotiations"
    >
      <span className="shrink-0 text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold mr-1">
        Negotiating
      </span>
      {activeJobs.map((l) => {
        const status = l.job_status ?? "";
        return (
          <button
            key={l.job_id}
            type="button"
            onClick={() => l.job_id && onOpen(l.job_id)}
            className={cn(
              "shrink-0 inline-flex items-center gap-2 rounded-full border bg-paper",
              "px-3 py-1 text-caption font-medium text-ink hover:bg-paper-3 transition"
            )}
            style={{ borderColor: "rgba(15,15,15,0.12)" }}
            role="listitem"
          >
            <span
              aria-hidden
              className={cn("size-2 rounded-full", statusDot(status))}
            />
            <span className="truncate max-w-[200px]">
              {shortTitle(l.title)}
            </span>
            <span className="text-micro text-ink-3">
              {statusLabel(status)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function statusDot(s: string): string {
  if (s === "awaiting_user_approval") return "bg-orange";
  if (s === "awaiting_seller_reply") return "bg-yellow-deep";
  return "bg-green";
}

function statusLabel(s: string): string {
  switch (s) {
    case "active":
      return "active";
    case "awaiting_user_approval":
      return "needs approval";
    case "awaiting_seller_reply":
      return "waiting reply";
    default:
      return s;
  }
}

function shortTitle(t: string): string {
  if (!t) return "Negotiation";
  if (t.length > 28) return t.slice(0, 25) + "…";
  return t;
}
