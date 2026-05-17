"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useNotifications } from "@/lib/notifications-context";
import { cn, relativeTime } from "@/lib/utils";
import type { Notification, NotificationKind } from "@/types";

interface ActivityBellProps {
  className?: string;
}

const KIND_DOT: Record<NotificationKind, string> = {
  clarifying_question: "var(--orange)",
  listings_found: "var(--yellow)",
  approval_needed: "var(--orange)",
  seller_replied: "var(--green)",
  deal_closed: "var(--green)",
  error: "var(--accent)",
  info: "var(--ink-3, #6b7280)",
};

const KIND_LABEL: Record<NotificationKind, string> = {
  clarifying_question: "Goti needs your input",
  listings_found: "Products found",
  approval_needed: "Approval needed",
  seller_replied: "Seller replied",
  deal_closed: "Deal closed",
  error: "Goti hit an error",
  info: "Update",
};

/**
 * Top-right activity entry. Click toggles a small dropdown panel anchored
 * below-right of the bell with notification rows; clicking a row routes
 * via `target_href` and closes the panel. Click-outside dismisses.
 *
 * The data is provided by the SSE-backed NotificationsProvider context.
 * The badge shows live `unreadCount`; rows show the newest 10 entries.
 */
export function ActivityBell({ className }: ActivityBellProps) {
  const router = useRouter();
  const { notifications, unreadCount, markRead } = useNotifications();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const showBadge = unreadCount > 0;
  // Show the newest 10 — the SSE provider keeps the array newest-first.
  const visible = notifications.slice(0, 10);

  useEffect(() => {
    if (!open) return;
    function onMouseDown(e: MouseEvent) {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function handleSelect(n: Notification) {
    setOpen(false);
    // Fire-and-forget: mark read in the background and navigate.
    if (n.status === "unread") {
      void markRead(n.id);
    }
    if (n.target_href) {
      router.push(n.target_href);
    }
  }

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Activity${showBadge ? `, ${unreadCount} unread` : ""}`}
        aria-expanded={open}
        aria-haspopup="menu"
        className={cn(
          "relative inline-flex items-center justify-center size-9 rounded-2xl border bg-paper text-ink-2",
          "transition-colors hover:bg-paper-2 hover:text-ink",
          open && "bg-paper-2 text-ink"
        )}
        style={{ borderColor: "rgba(15,15,15,0.12)" }}
      >
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          className="size-[18px]"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M6 8a6 6 0 0 1 12 0c0 4 1.5 6 2 7H4c.5-1 2-3 2-7Z" />
          <path d="M10 19a2 2 0 0 0 4 0" />
        </svg>
        {showBadge ? (
          <span
            aria-hidden
            className="absolute -top-1 -right-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-semibold leading-none text-white"
            style={{ background: "var(--accent)" }}
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        ) : null}
        <span className="sr-only">Activity</span>
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="Activity notifications"
          // Opens UPWARD (``bottom-...``) because ActivityBell lives at
          // the bottom of the LEFT sidebar — a default top-anchored
          // dropdown would clip off the viewport bottom.
          // Opens RIGHTWARD (``left-0``) because we're on the left edge
          // of the viewport — anchoring to the button's right edge
          // would extend the 340px panel off-screen to the left.
          className={cn(
            "absolute left-0 bottom-[calc(100%+8px)] z-40 w-[340px] rounded-2xl bg-paper p-3 border"
          )}
          style={{
            borderColor: "var(--ink-line)",
            boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
          }}
        >
          <div className="px-1 pt-1 pb-2 text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
            Activity ({unreadCount})
          </div>
          {visible.length === 0 ? (
            <div className="px-2.5 py-6 text-center text-caption text-ink-3">
              No notifications yet.
            </div>
          ) : (
            <ul className="flex flex-col">
              {visible.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => handleSelect(n)}
                    className={cn(
                      "group w-full text-left flex items-start gap-2.5 rounded-xl px-2.5 py-2",
                      "hover:bg-paper-2 transition-colors",
                      n.status === "unread" ? "" : "opacity-70"
                    )}
                  >
                    <span
                      aria-hidden
                      className="mt-1.5 inline-block size-2 rounded-full shrink-0"
                      style={{ background: KIND_DOT[n.kind] ?? "var(--ink-3, #6b7280)" }}
                    />
                    <span className="flex-1 min-w-0 flex flex-col leading-tight">
                      <span className="text-body text-ink leading-snug line-clamp-2">
                        {n.title}
                      </span>
                      <span className="text-caption text-ink-2 mt-0.5 flex items-center gap-1.5">
                        <span>{KIND_LABEL[n.kind] ?? "Update"}</span>
                        {n.created_at ? (
                          <>
                            <span className="text-ink-3">·</span>
                            <span className="text-ink-3">
                              {relativeTime(n.created_at)}
                            </span>
                          </>
                        ) : null}
                      </span>
                    </span>
                    <span
                      aria-hidden
                      className="text-ink-3 group-hover:text-ink mt-1 shrink-0"
                    >
                      →
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
