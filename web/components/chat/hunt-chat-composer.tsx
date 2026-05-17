"use client";

// Bottom composer for /c/<hunt_id>. Behaviour adapts to hunt state:
//
// - Hunt has a pending clarifying_question notification → composer
//   captures the answer + POSTs the approval decision so the clarifier
//   reasoner resumes.
// - Hunt is in any other state → composer is disabled with a "Goti is
//   working…" hint. (Future: ad-hoc instructions during a hunt.)

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { submitApprovalDecision } from "@/lib/api-client";
import { useNotifications } from "@/lib/notifications-context";
import { cn } from "@/lib/utils";
import type { HuntState, Notification } from "@/types";

interface Props {
  huntId: string;
  hunt: HuntState | null;
}

export function HuntChatComposer({ huntId, hunt }: Props) {
  const router = useRouter();
  const { notifications, markRead } = useNotifications();
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Find any unresolved clarifying_question for this hunt — that's
  // what gates the composer being interactive.
  const pendingClarify: Notification | null = useMemo(() => {
    return (
      notifications.find(
        (n) =>
          n.hunt_id === huntId &&
          n.kind === "clarifying_question" &&
          n.status !== "resolved" &&
          n.status !== "dismissed"
      ) ?? null
    );
  }, [notifications, huntId]);

  const clarifyQuestion =
    (pendingClarify?.payload?.question as string | undefined) ??
    pendingClarify?.title ??
    "";

  const isClarifying = pendingClarify !== null;
  const huntClosed = hunt?.status === "closed" || hunt?.status === "error";
  const disabled = submitting || draft.trim().length === 0 || !isClarifying;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isClarifying || !pendingClarify?.approval_request_id) {
      return;
    }
    const text = draft.trim();
    if (!text) return;

    // Try to parse as a number for budget questions. If it parses,
    // pass it as `{budget}`; otherwise pass as `{answer}` (free-form).
    const numeric = Number.parseFloat(text.replace(/[^0-9.]/g, ""));
    const looksLikeBudget = /budget/i.test(clarifyQuestion);
    const feedback =
      looksLikeBudget && Number.isFinite(numeric) && numeric > 0
        ? { budget: numeric }
        : { answer: text };

    setError(null);
    setSubmitting(true);
    try {
      await submitApprovalDecision(
        pendingClarify.approval_request_id,
        "approve",
        feedback
      );
      if (pendingClarify.status === "unread") {
        await markRead(pendingClarify.id).catch(() => undefined);
      }
      setDraft("");
      // Trigger a soft refresh so the hunt state updates promptly.
      router.refresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Couldn't send your answer — try again."
      );
    } finally {
      setSubmitting(false);
    }
  }

  // Helper text shown above the input when idle.
  const helper = isClarifying
    ? `Goti is asking: ${clarifyQuestion}`
    : huntClosed
      ? "This hunt is closed. Start a new hunt to keep going."
      : "Goti is working — watch the chat above for updates.";

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <p
        className={cn(
          "text-caption",
          isClarifying ? "text-ink" : "text-ink-3"
        )}
      >
        {helper}
      </p>
      <div
        className={cn(
          "flex items-end gap-2 rounded-2xl border bg-paper px-3 py-2",
          "focus-within:ring-2 focus-within:ring-orange/40 focus-within:border-orange transition",
          (!isClarifying || submitting) && "opacity-70"
        )}
        style={{ borderColor: "var(--ink-line)" }}
      >
        <textarea
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!disabled) {
                handleSubmit(e as unknown as React.FormEvent);
              }
            }
          }}
          placeholder={
            isClarifying
              ? "Type your answer…"
              : "Goti is working — replies open up here when needed."
          }
          disabled={!isClarifying || submitting}
          className={cn(
            "flex-1 resize-none bg-transparent text-body text-ink placeholder:text-ink-3",
            "outline-none disabled:cursor-not-allowed py-1"
          )}
          style={{ minHeight: 28, maxHeight: 140 }}
        />
        <button
          type="submit"
          disabled={disabled}
          className={cn(
            "inline-flex items-center gap-1 rounded-lg bg-orange text-paper font-semibold px-3 py-1.5 text-caption",
            "border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95 transition",
            "disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none"
          )}
        >
          {submitting ? "Sending…" : "Send"}
          <span aria-hidden>→</span>
        </button>
      </div>
      {error ? (
        <p className="text-caption text-accent" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
