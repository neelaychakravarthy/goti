"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface ActivityBellProps {
  className?: string;
  /** Approval-waiting count rendered in the orange badge. */
  count?: number;
}

type NotificationKind = "approval" | "products" | "reply" | "better_offer";

interface NotificationItem {
  id: string;
  kind: NotificationKind;
  title: string;
  sub: string;
  href: string;
}

const KIND_DOT: Record<NotificationKind, string> = {
  approval: "var(--orange)",
  products: "var(--yellow)",
  reply: "var(--green)",
  better_offer: "var(--orange)",
};

const KIND_LABEL: Record<NotificationKind, string> = {
  approval: "Approval needed",
  products: "Products found",
  reply: "Seller replied",
  better_offer: "Better offer found",
};

const NOTIFICATIONS: NotificationItem[] = [
  {
    id: "n-approval-desk",
    kind: "approval",
    title: "Standing desk: 3 messages waiting for approval",
    sub: KIND_LABEL.approval,
    href: "/approve?hunt=standing-desk",
  },
  {
    id: "n-products-lebron",
    kind: "products",
    title: "LeBron basketball shoes: 4 options found",
    sub: KIND_LABEL.products,
    href: "/search?hunt=lebron",
  },
  {
    id: "n-reply-couch",
    kind: "reply",
    title: "Couch near SF: seller replied",
    sub: KIND_LABEL.reply,
    href: "/search?hunt=couch",
  },
  {
    id: "n-better-desk",
    kind: "better_offer",
    title: "Standing desk: Maya accepted $195",
    sub: KIND_LABEL.better_offer,
    href: "/deal/j-flexispot",
  },
];

/**
 * Top-right activity entry. Click toggles a small dropdown panel anchored
 * below-right of the bell with 4 notification rows; clicking a row routes and
 * closes the panel. Click-outside dismisses.
 */
export function ActivityBell({ className, count = 3 }: ActivityBellProps) {
  const router = useRouter();
  const showBadge = count > 0;
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

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

  function handleSelect(href: string) {
    setOpen(false);
    router.push(href);
  }

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Activity${showBadge ? `, ${count} waiting` : ""}`}
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
            {count}
          </span>
        ) : null}
        <span className="sr-only">Activity</span>
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="Activity notifications"
          className={cn(
            "absolute right-0 top-[calc(100%+8px)] z-40 w-[340px] rounded-2xl bg-paper p-3 border"
          )}
          style={{
            borderColor: "var(--ink-line)",
            boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
          }}
        >
          <div className="px-1 pt-1 pb-2 text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
            Activity ({count})
          </div>
          <ul className="flex flex-col">
            {NOTIFICATIONS.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => handleSelect(n.href)}
                  className={cn(
                    "group w-full text-left flex items-start gap-2.5 rounded-xl px-2.5 py-2",
                    "hover:bg-paper-2 transition-colors"
                  )}
                >
                  <span
                    aria-hidden
                    className="mt-1.5 inline-block size-2 rounded-full shrink-0"
                    style={{ background: KIND_DOT[n.kind] }}
                  />
                  <span className="flex-1 min-w-0 flex flex-col leading-tight">
                    <span className="text-body text-ink leading-snug">
                      {n.title}
                    </span>
                    <span className="text-caption text-ink-2 mt-0.5">
                      {n.sub}
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
        </div>
      ) : null}
    </div>
  );
}
