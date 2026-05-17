"use client";

// Phase N — polymorphic message renderer for the Main tab of the
// chat-first hunt page. Combines:
//
// - HuntActivityEvent rows (existing reasoning timeline).
// - Listings-found notifications (rendered as inline narrow listing
//   cards).
// - Approval-needed notifications (rendered as inline approval cards
//   for hunt-scoped approvals; per-job approvals show a link to the
//   relevant negotiation tab).
// - Task started / completed / errored notifications (status pills).
// - Analyzer progress / complete events (Phase G' tagging).
//
// Source events: on mount we fetch the durable activity rows via
// GET /api/hunts/{id}/activity (hydration), then subscribe to the
// notifications SSE stream via useNotifications() for live updates.
// Phase P of the followups round dropped the prior 3s polling — every
// activity event the backend writes now also publishes onto the
// notifications queue with payload.kind_tag="hunt_activity", so the
// SSE channel delivers real-time updates without round-tripping the
// activity endpoint.

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { InlineApprovalCard } from "@/components/chat/inline-approval-card";
import { InlineListingCard } from "@/components/chat/inline-listing-card";
import { useNotifications } from "@/lib/notifications-context";
import { getHuntActivity } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { HuntActivityEvent, Notification } from "@/types";

// Auto-scroll threshold — if the user is within this many pixels of
// the bottom when a new message arrives, we smooth-scroll to keep
// them anchored. Otherwise we leave them alone (they're reading older
// messages and a bump would be disruptive).
const AUTOSCROLL_THRESHOLD_PX = 80;

interface Props {
  huntId: string;
  /** Callback fired when the user clicks "Start negotiation" inside an
   *  inline listing card — the parent page promotes the new job into
   *  the tab strip. */
  onNegotiationStarted?: (jobId: string) => void;
  className?: string;
}

interface BaseMsg {
  id: string;
  created_at: string;
}

type RenderableMsg =
  | (BaseMsg & {
      kind: "activity";
      event: HuntActivityEvent;
    })
  | (BaseMsg & {
      kind: "listing_discovered";
      listing: {
        id: string;
        title: string;
        price: number;
        marketplace: string;
        url?: string;
        image_url?: string | null;
        description?: string | null;
        location?: string | null;
      };
      target_price: number | null;
    })
  | (BaseMsg & {
      kind: "approval";
      title: string;
      body: string;
      target_href: string;
    })
  | (BaseMsg & {
      kind: "task";
      status: "started" | "completed" | "errored";
      label: string;
      summary?: string;
      task_kind: string;
    })
  | (BaseMsg & {
      kind: "analyzer";
      stage: "progress" | "complete";
      label: string;
      summary?: string;
    });

export function HuntConversation({
  huntId,
  onNegotiationStarted,
  className,
}: Props) {
  const [activity, setActivity] = useState<HuntActivityEvent[]>([]);
  const [loaded, setLoaded] = useState(false);
  const { notifications } = useNotifications();

  // Phase P — initial hydration only. The 3s setInterval was dropped;
  // live updates arrive via the notifications SSE stream which
  // includes ``payload.kind_tag === "hunt_activity"`` events emitted
  // by the backend's record_activity helper.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const rows = await getHuntActivity(huntId);
        if (!cancelled) {
          setActivity(rows);
          setLoaded(true);
        }
      } catch {
        if (!cancelled) setLoaded(true);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [huntId]);

  const messages = useMemo(
    () => buildMessageList(huntId, activity, notifications),
    [huntId, activity, notifications],
  );

  // Phase S — auto-scroll. Pattern from
  // ``web/components/hunt-activity-timeline.tsx`` (around line 150).
  // We anchor to the bottom-sentinel when the user is within
  // AUTOSCROLL_THRESHOLD_PX of the bottom; otherwise we leave them
  // alone so reading older messages isn't disrupted.
  const containerRef = useRef<HTMLOListElement | null>(null);
  const endRef = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    const end = endRef.current;
    if (!container || !end) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceFromBottom <= AUTOSCROLL_THRESHOLD_PX) {
      try {
        end.scrollIntoView({ behavior: "smooth", block: "end" });
      } catch {
        // older browsers: noop
      }
    }
  }, [messages.length]);

  if (!loaded) {
    return (
      <div
        className={cn(
          "rounded-2xl border bg-paper-2 px-4 py-3 text-caption text-ink-3",
          className,
        )}
        style={{ borderColor: "rgba(15,15,15,0.08)" }}
        aria-live="polite"
      >
        Loading conversation…
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div
        className={cn(
          "rounded-2xl border bg-paper-2 px-4 py-6 text-caption text-ink-3 text-center",
          className,
        )}
        style={{ borderColor: "rgba(15,15,15,0.08)" }}
      >
        Goti hasn&rsquo;t reasoned about this hunt yet. As soon as discovery,
        valuation, or analysis runs, it&rsquo;ll show up here.
      </div>
    );
  }

  return (
    <ol
      ref={containerRef}
      className={cn(
        "flex flex-col gap-3 rounded-2xl border bg-paper-2 px-4 py-4 max-h-[70vh] overflow-y-auto",
        className,
      )}
      style={{ borderColor: "rgba(15,15,15,0.08)" }}
      aria-label="Hunt conversation"
    >
      {messages.map((msg) => (
        <li key={msg.id} className="flex flex-col gap-1">
          <MessageRenderer
            msg={msg}
            huntId={huntId}
            onNegotiationStarted={onNegotiationStarted}
          />
        </li>
      ))}
      <li
        ref={endRef}
        aria-hidden="true"
        className="h-px"
      />
    </ol>
  );
}

function MessageRenderer({
  msg,
  huntId,
  onNegotiationStarted,
}: {
  msg: RenderableMsg;
  huntId: string;
  onNegotiationStarted?: (jobId: string) => void;
}) {
  const stamp = formatStamp(msg.created_at);

  if (msg.kind === "activity") {
    return <ActivityRow event={msg.event} stamp={stamp} />;
  }
  if (msg.kind === "listing_discovered") {
    return (
      <div className="flex flex-col gap-1">
        <RowHeader label="New candidate" stamp={stamp} dot="var(--yellow, #d97706)" />
        <InlineListingCard
          huntId={huntId}
          listing={msg.listing}
          targetPrice={msg.target_price}
          onStarted={onNegotiationStarted}
        />
      </div>
    );
  }
  if (msg.kind === "approval") {
    return (
      <div className="flex flex-col gap-1">
        <RowHeader
          label="Approval needed"
          stamp={stamp}
          dot="var(--orange, #f97316)"
        />
        <InlineApprovalCard
          title={msg.title}
          body={msg.body}
          targetHref={msg.target_href}
        />
      </div>
    );
  }
  if (msg.kind === "task") {
    return <TaskStatusRow msg={msg} stamp={stamp} />;
  }
  // analyzer
  return <AnalyzerRow msg={msg} stamp={stamp} />;
}

function RowHeader({
  label,
  stamp,
  dot,
}: {
  label: string;
  stamp: string;
  dot: string;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span
        aria-hidden
        className="inline-flex size-2 rounded-full mt-1"
        style={{ background: dot }}
      />
      <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
        {label}
      </span>
      {stamp ? (
        <span className="text-micro text-ink-3 ml-auto">{stamp}</span>
      ) : null}
    </div>
  );
}

function ActivityRow({
  event,
  stamp,
}: {
  event: HuntActivityEvent;
  stamp: string;
}) {
  const phase = event.phase || "reasoning";
  const label = PHASE_LABEL[phase] ?? phase;
  const dot = PHASE_DOT[phase] ?? "var(--ink-3, #6b7280)";
  const isQueued = event.step_idx === 0;

  return (
    <div className="flex flex-col gap-1">
      <RowHeader
        label={isQueued ? "queued" : label}
        stamp={stamp}
        dot={dot}
      />
      {event.next_goal ? (
        <p className="text-caption text-ink mt-0.5">
          <span className="text-ink-3 mr-1">Goal:</span>
          {event.next_goal}
        </p>
      ) : null}
      {event.action_summary ? (
        <p className="text-caption text-ink-2 mt-0.5">
          <span className="text-ink-3 mr-1">Action:</span>
          <code className="text-caption">{event.action_summary}</code>
        </p>
      ) : null}
      {event.thinking ? (
        <p className="text-caption text-ink-2 mt-1 whitespace-pre-wrap leading-relaxed">
          {event.thinking}
        </p>
      ) : null}
    </div>
  );
}

function TaskStatusRow({
  msg,
  stamp,
}: {
  msg: Extract<RenderableMsg, { kind: "task" }>;
  stamp: string;
}) {
  const tone =
    msg.status === "errored"
      ? "border-orange/40 bg-paper text-orange"
      : msg.status === "completed"
        ? "border-green/40 bg-green-soft text-green"
        : "border-ink-line/20 bg-paper-2 text-ink-2";
  const dot =
    msg.status === "errored"
      ? "var(--orange, #f97316)"
      : msg.status === "completed"
        ? "var(--green, #16a34a)"
        : "var(--ink-3, #6b7280)";
  return (
    <div className="flex flex-col gap-1">
      <RowHeader
        label={
          msg.status === "started"
            ? "started"
            : msg.status === "completed"
              ? "finished"
              : "errored"
        }
        stamp={stamp}
        dot={dot}
      />
      <span
        className={cn(
          "self-start inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-caption font-medium",
          tone
        )}
      >
        {msg.label}
        {msg.summary ? (
          <span className="text-micro text-ink-3 font-mono">{msg.summary}</span>
        ) : null}
      </span>
    </div>
  );
}

function AnalyzerRow({
  msg,
  stamp,
}: {
  msg: Extract<RenderableMsg, { kind: "analyzer" }>;
  stamp: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <RowHeader
        label={msg.stage === "complete" ? "lessons captured" : "analyzing"}
        stamp={stamp}
        dot="var(--orange, #f97316)"
      />
      <p className="text-caption text-ink leading-relaxed">{msg.label}</p>
      {msg.stage === "complete" ? (
        <Link
          href="/playbook"
          className="self-start text-caption text-ink-2 underline-offset-2 hover:underline"
        >
          View in Memory →
        </Link>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Source-of-truth — merge activity rows + notifications into a single
// chronologically-sorted message list.

function buildMessageList(
  huntId: string,
  activity: HuntActivityEvent[],
  notifications: Notification[],
): RenderableMsg[] {
  const out: RenderableMsg[] = [];
  // Dedupe key — when a hunt_activity SSE event arrives BEFORE the
  // initial-fetch activity list refreshes, we'd otherwise render the
  // same logical event twice (once via the hydrated row, once via the
  // SSE-fed activity entry). Keying on the activity row id (stored on
  // both sides as ``activity_id``) keeps the timeline single-sourced.
  const seenActivityIds = new Set<string>();

  // Activity phases that live in OTHER UI surfaces — exclude them
  // from the chat feed to keep it focused on reasoning + status
  // updates. Listings live in the right-side CandidatesPanel; task
  // start/complete events are already shown as TaskStatusStrip pills
  // at the top of the chat.
  const CHAT_HIDDEN_PHASES = new Set<string>([
    "listing_discovered",
  ]);

  for (const ev of activity) {
    if (CHAT_HIDDEN_PHASES.has(ev.phase ?? "")) {
      seenActivityIds.add(ev.id);
      continue;
    }
    out.push({
      kind: "activity",
      event: ev,
      id: `activity:${ev.id}`,
      created_at: ev.created_at ?? "",
    });
    seenActivityIds.add(ev.id);
  }

  for (const notif of notifications) {
    if (notif.hunt_id && notif.hunt_id !== huntId) continue;
    const payload = (notif.payload ?? {}) as Record<string, unknown>;
    const created = notif.created_at ?? "";

    // Phase P — hunt_activity events arriving via SSE. Render them as
    // activity rows so the timeline merges live + hydrated state.
    const kindTagEarly =
      typeof payload.kind_tag === "string" ? payload.kind_tag : "";
    if (kindTagEarly === "hunt_activity") {
      const activityId = String(payload.activity_id ?? notif.id);
      if (seenActivityIds.has(activityId)) continue;
      const phase = String(payload.phase ?? "reasoning");
      // Same hidden-phase filter as the hydrated path above.
      if (CHAT_HIDDEN_PHASES.has(phase)) {
        seenActivityIds.add(activityId);
        continue;
      }
      const synthEvent: HuntActivityEvent = {
        id: activityId,
        hunt_id: String(payload.hunt_id ?? notif.hunt_id ?? huntId),
        job_id:
          typeof payload.job_id === "string"
            ? (payload.job_id as string)
            : (notif.job_id ?? null),
        phase,
        step_idx: typeof payload.step_idx === "number"
          ? (payload.step_idx as number)
          : 1,
        thinking:
          typeof payload.thinking === "string"
            ? (payload.thinking as string)
            : null,
        next_goal:
          typeof payload.next_goal === "string"
            ? (payload.next_goal as string)
            : null,
        action_summary:
          typeof payload.action_summary === "string"
            ? (payload.action_summary as string)
            : null,
        url:
          typeof payload.url === "string" ? (payload.url as string) : null,
        created_at:
          typeof payload.created_at === "string"
            ? (payload.created_at as string)
            : (notif.created_at ?? null),
      };
      out.push({
        kind: "activity",
        event: synthEvent,
        id: `activity:${activityId}`,
        created_at: synthEvent.created_at ?? "",
      });
      seenActivityIds.add(activityId);
      continue;
    }

    if (notif.kind === "listings_found") {
      // Discovered listings live in the right-side CandidatesPanel,
      // NOT inline in the chat. Drop the notification from the chat
      // feed; the panel polls its own data source.
      continue;
    }

    if (notif.kind === "clarifying_question" || notif.kind === "approval_needed") {
      out.push({
        kind: "approval",
        title: notif.title || "Approval needed",
        body: notif.body || "",
        target_href: notif.target_href || `/chat?hunt_id=${huntId}`,
        id: `approval:${notif.id}`,
        created_at: created,
      });
      continue;
    }

    const kindTag = typeof payload.kind_tag === "string" ? payload.kind_tag : "";
    if (kindTag === "task_started" || kindTag === "task_completed" || kindTag === "task_errored") {
      const taskKind = String(payload.task_kind ?? "");
      out.push({
        kind: "task",
        status:
          kindTag === "task_started"
            ? "started"
            : kindTag === "task_completed"
              ? "completed"
              : "errored",
        label: String(payload.label ?? notif.title ?? ""),
        summary: typeof payload.summary === "string" ? payload.summary : undefined,
        task_kind: taskKind,
        id: `task:${notif.id}`,
        created_at: created,
      });
      continue;
    }

    if (kindTag === "discovery_complete") {
      // Already covered by task_completed for the discovery task;
      // surface as a friendly note only if no matching task event.
      out.push({
        kind: "analyzer",
        stage: "complete",
        label: notif.body || "Discovery complete.",
        id: `discovery_done:${notif.id}`,
        created_at: created,
      });
      continue;
    }
  }

  out.sort((a, b) => {
    const aTs = a.created_at || "";
    const bTs = b.created_at || "";
    if (aTs === bTs) return a.id < b.id ? -1 : 1;
    return aTs < bTs ? -1 : 1;
  });
  return out;
}

function formatStamp(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

const PHASE_LABEL: Record<string, string> = {
  discovery: "searching marketplaces",
  send_message: "sending message",
  fetch_replies: "checking for replies",
  reasoning: "reasoning",
};

const PHASE_DOT: Record<string, string> = {
  discovery: "var(--yellow, #d97706)",
  send_message: "var(--green, #16a34a)",
  fetch_replies: "#8b5cf6",
  reasoning: "var(--ink-3, #6b7280)",
};
