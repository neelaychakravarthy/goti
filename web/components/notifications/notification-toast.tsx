"use client";

// Transient toast for new unread notifications. Subscribes to
// useNotifications() and tracks which ids have already been "toasted"
// in a `Set<string>` ref so the toast doesn't reappear on context-state
// churn or when the user marks-read later.
//
// Visual shape: fixed bottom-right card stack. Auto-dismiss after 6s.
// Click navigates to `target_href` and marks read.

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { useNotifications } from "@/lib/notifications-context";
import type { Notification, NotificationKind } from "@/types";

const TOAST_TTL_MS = 6000;

const KIND_DOT: Record<NotificationKind, string> = {
  clarifying_question: "var(--orange)",
  listings_found: "var(--yellow)",
  approval_needed: "var(--orange)",
  seller_replied: "var(--green)",
  deal_closed: "var(--green)",
  error: "var(--accent)",
  info: "var(--ink-3, #6b7280)",
};

interface ActiveToast {
  notification: Notification;
  /** epoch ms when the toast appeared — drives the auto-dismiss timer. */
  appearedAt: number;
}

export function NotificationToast() {
  const router = useRouter();
  const { notifications, markRead } = useNotifications();
  const [active, setActive] = useState<ActiveToast[]>([]);
  // Tracks every notification id we've already raised a toast for,
  // even after dismissal — prevents re-toasting on revisit.
  const toastedRef = useRef<Set<string>>(new Set<string>());
  // First-pass guard: on initial mount we *seed* the toasted-set with
  // every existing notification so the SSE snapshot doesn't fire 50 toasts.
  const seededRef = useRef(false);

  useEffect(() => {
    if (!seededRef.current) {
      // Initial render: snapshot every id we already know about so they
      // don't get toasted. Only NEW ids arriving after this point fire.
      for (const n of notifications) toastedRef.current.add(n.id);
      seededRef.current = true;
      return;
    }
    // Subsequent renders: any unread notification we haven't toasted yet
    // becomes a fresh toast.
    const fresh = notifications.filter(
      (n) =>
        n.status === "unread" && !toastedRef.current.has(n.id)
    );
    if (fresh.length === 0) return;
    const now = Date.now();
    for (const n of fresh) toastedRef.current.add(n.id);
    setActive((prev) => [
      ...prev,
      ...fresh.map((notification) => ({ notification, appearedAt: now })),
    ]);
  }, [notifications]);

  // Auto-dismiss expired toasts.
  useEffect(() => {
    if (active.length === 0) return;
    const interval = window.setInterval(() => {
      const now = Date.now();
      setActive((prev) =>
        prev.filter((t) => now - t.appearedAt < TOAST_TTL_MS)
      );
    }, 500);
    return () => window.clearInterval(interval);
  }, [active.length]);

  const visible = useMemo(() => active.slice(-3), [active]);

  if (visible.length === 0) return null;

  async function handleClick(notification: Notification) {
    setActive((prev) =>
      prev.filter((t) => t.notification.id !== notification.id),
    );
    // Navigate FIRST so a flaky markRead never silently swallows the
    // click. Mark-read is best-effort behind the navigation.
    if (notification.target_href) {
      router.push(notification.target_href);
    }
    try {
      await markRead(notification.id);
    } catch {
      // ignored — notification list will reconcile on next SSE tick
    }
  }

  function handleDismiss(id: string) {
    setActive((prev) => prev.filter((t) => t.notification.id !== id));
  }

  return (
    <div
      aria-live="polite"
      aria-label="New notifications"
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-[380px] w-[calc(100vw-2rem)] sm:w-[380px] pointer-events-none"
    >
      {visible.map((t) => (
        <article
          key={t.notification.id}
          role="status"
          className={cn(
            "pointer-events-auto rounded-2xl bg-paper p-3 border shadow-[0_8px_24px_rgba(0,0,0,0.10)]",
            "flex items-start gap-2.5 animate-in fade-in slide-in-from-bottom-2"
          )}
          style={{ borderColor: "var(--ink-line)" }}
        >
          <span
            aria-hidden
            className="mt-1.5 inline-block size-2 rounded-full shrink-0"
            style={{ background: KIND_DOT[t.notification.kind] ?? "var(--ink-3, #6b7280)" }}
          />
          <button
            type="button"
            onClick={() => handleClick(t.notification)}
            className="flex-1 min-w-0 text-left"
          >
            <div className="text-body text-ink font-medium leading-snug">
              {t.notification.title}
            </div>
            {t.notification.body ? (
              <div className="text-caption text-ink-2 mt-0.5 line-clamp-2">
                {t.notification.body}
              </div>
            ) : null}
          </button>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => handleDismiss(t.notification.id)}
            className="shrink-0 inline-flex size-6 items-center justify-center rounded-md text-ink-3 hover:text-ink hover:bg-paper-2 transition-colors"
          >
            <svg
              aria-hidden
              viewBox="0 0 24 24"
              className="size-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M6 6 18 18" />
              <path d="M18 6 6 18" />
            </svg>
          </button>
        </article>
      ))}
    </div>
  );
}
