"use client";

// Phase M — Inbox panel pinned at the top of the HuntSidebar. Lists
// cross-hunt pending approvals + jobs flagged ready_to_close. Polls
// /api/inbox every 5s and refreshes on every notifications-stream
// event so the badge updates live.

import Link from "next/link";
import { useEffect, useState } from "react";

import { getInbox } from "@/lib/api-client";
import { useNotifications } from "@/lib/notifications-context";
import { cn } from "@/lib/utils";
import type { InboxItem } from "@/types";

const POLL_INTERVAL_MS = 5_000;

interface Props {
  className?: string;
}

export function InboxPanel({ className }: Props) {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const { notifications } = useNotifications();
  const notifCount = notifications.length;

  // Single effect drives both the poll loop and the
  // refresh-on-notification trigger. ``notifCount`` as a dep means a
  // new notification re-mounts the effect, which fires an immediate
  // load() before resuming the 5s cadence.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const body = await getInbox();
        if (cancelled) return;
        setItems(body.items ?? []);
      } catch {
        // Silent — the badge just stays at its previous value.
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [notifCount]);

  const total = items.length;

  return (
    <section
      className={cn(
        "rounded-2xl border bg-paper px-3 py-2 flex flex-col gap-1.5",
        className,
      )}
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
      aria-label="Inbox"
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center justify-between gap-2 text-left"
      >
        <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
          Inbox{" "}
          <span className="text-ink-2 font-mono">({total})</span>
        </span>
        <span className="text-micro text-ink-3" aria-hidden>
          {expanded ? "▾" : "▸"}
        </span>
      </button>

      {expanded ? (
        loaded && items.length === 0 ? (
          <p className="text-micro text-ink-3 italic">
            Nothing waiting on you.
          </p>
        ) : (
          <ul className="flex flex-col gap-1 max-h-[220px] overflow-y-auto">
            {items.map((it) => (
              <li key={inboxKey(it)}>
                <Link
                  href={it.target_href}
                  className={cn(
                    "block rounded-lg px-2 py-1.5 text-micro text-ink",
                    "hover:bg-paper-3 transition-colors"
                  )}
                >
                  <div className="flex items-baseline gap-1.5">
                    <span
                      aria-hidden
                      className="inline-flex size-1.5 rounded-full mt-1.5"
                      style={{ background: dotForKind(it.kind) }}
                    />
                    <span className="leading-snug">{it.label}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </section>
  );
}

function dotForKind(kind: string): string {
  switch (kind) {
    case "approval":
      return "var(--orange, #f97316)";
    case "ready_to_close":
      return "var(--green, #16a34a)";
    default:
      return "var(--ink-3, #6b7280)";
  }
}

function inboxKey(it: InboxItem): string {
  return `${it.kind}:${it.approval_request_id ?? it.job_id ?? it.hunt_id ?? "x"}`;
}
