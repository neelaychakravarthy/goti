"use client";

// Client-side notifications context. Wires the React tree to the backend's
// `/api/notifications` HTTP snapshot + `/api/notifications/stream` SSE feed.
//
// Every backend request requires `Authorization: Bearer <google_id_token>`.
// We read the token from the NextAuth session client-side (via
// `/api/auth/session`) and forward it. For SSE (EventSource can't set
// headers) we pass the token via the `?token=` query param — the
// backend's `optional_current_user` dependency handles both shapes.
//
// The provider:
//   1. On mount: fetches the session → snapshot via HTTP → opens SSE.
//   2. Merges every `event: notification` into the in-memory list
//      (dedupe by id; newest-first).
//   3. Exposes `markRead(id)` which POSTs `/api/notifications/{id}/read`
//      with the same Authorization header.
//
// Heartbeat `event: ping` payloads are ignored on the client; the backend
// emits one every 30s to keep proxies from buffering.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { Notification } from "@/types";
import { getCachedIdToken } from "@/lib/session-token";

interface NotificationsContextValue {
  notifications: Notification[];
  unreadCount: number;
  markRead: (id: string) => Promise<void>;
  isConnected: boolean;
}

const NotificationsContext =
  createContext<NotificationsContextValue | null>(null);

export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext);
  if (!ctx) {
    throw new Error(
      "useNotifications must be used inside <NotificationsProvider>"
    );
  }
  return ctx;
}

interface NotificationsProviderProps {
  children: React.ReactNode;
}

async function _fetchSessionToken(): Promise<string | null> {
  // Shared cache — a single in-flight request is deduped across every
  // hook that calls this (api-client.ts, the notifications bootstrap,
  // markRead). Prevents `/api/auth/session` storms on busy pages.
  return getCachedIdToken();
}

export function NotificationsProvider({
  children,
}: NotificationsProviderProps) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
    let es: EventSource | null = null;

    async function bootstrap() {
      const idToken = await _fetchSessionToken();
      if (cancelled) return;

      // 1) Initial HTTP snapshot. Swallow errors — if the backend is down
      // the SSE channel will keep retrying and the UI degrades to empty.
      try {
        const headers: Record<string, string> = {};
        if (idToken) headers["Authorization"] = `Bearer ${idToken}`;
        const r = await fetch(`${apiBase}/api/notifications`, {
          cache: "no-store",
          headers,
        });
        if (r.ok) {
          const items = (await r.json()) as Notification[];
          if (!cancelled && Array.isArray(items)) {
            setNotifications(items);
          }
        }
      } catch {
        /* swallow — SSE will deliver the snapshot too on connect */
      }

      if (cancelled) return;

      // 2) SSE subscription. EventSource can't set Authorization, so we
      // pass the token via ``?token=`` (the backend's optional_current_user
      // dependency reads either).
      const tokenQS = idToken
        ? `?token=${encodeURIComponent(idToken)}`
        : "";
      try {
        es = new EventSource(`${apiBase}/api/notifications/stream${tokenQS}`);
      } catch {
        // EventSource ctor can throw on malformed URLs. If the host doesn't
        // support SSE the UI silently falls back to the HTTP snapshot.
        return;
      }
      eventSourceRef.current = es;

      es.onopen = () => {
        if (!cancelled) setIsConnected(true);
      };
      es.onerror = () => {
        if (!cancelled) setIsConnected(false);
        // EventSource auto-reconnects on most errors. Don't close here.
      };

      const handleNotification = (event: MessageEvent) => {
        try {
          const parsed = JSON.parse(event.data) as Notification;
          if (!parsed || typeof parsed.id !== "string") return;
          setNotifications((prev) => {
            // Dedupe by id (SSE snapshot may overlap the HTTP fetch).
            const filtered = prev.filter((n) => n.id !== parsed.id);
            return [parsed, ...filtered];
          });
        } catch {
          /* malformed event payload — skip */
        }
      };
      es.addEventListener("notification", handleNotification as EventListener);
      // Heartbeat — keep proxies honest; no-op on the client.
      const handlePing = () => {
        /* noop */
      };
      es.addEventListener("ping", handlePing);
    }

    bootstrap();

    return () => {
      cancelled = true;
      es?.close();
      eventSourceRef.current = null;
    };
  }, []);

  const markRead = useCallback(async (id: string) => {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
    // Optimistic update — flip the row to read immediately.
    setNotifications((prev) =>
      prev.map((n) =>
        n.id === id
          ? {
              ...n,
              status: "read",
              read_at: n.read_at ?? new Date().toISOString(),
            }
          : n
      )
    );
    try {
      const idToken = await _fetchSessionToken();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (idToken) headers["Authorization"] = `Bearer ${idToken}`;
      await fetch(
        `${apiBase}/api/notifications/${encodeURIComponent(id)}/read`,
        {
          method: "POST",
          headers,
          cache: "no-store",
        }
      );
    } catch {
      /* swallow — UI already reflects the read state */
    }
  }, []);

  const unreadCount = notifications.filter(
    (n) => n.status === "unread"
  ).length;

  return (
    <NotificationsContext.Provider
      value={{ notifications, unreadCount, markRead, isConnected }}
    >
      {children}
    </NotificationsContext.Provider>
  );
}
