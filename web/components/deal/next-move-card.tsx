"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { FinalizeCloseModal } from "@/components/deal/finalize-close-modal";
import { PriceLadderView } from "@/components/deal/price-ladder";
import { SavingsReceiptView } from "@/components/deal/savings-receipt";
import { draftNext, submitApprovalDecision } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { NextMove } from "@/types";

interface NextMoveCardProps {
  move: NextMove;
  /** When present, the Approve button submits a real decision against
   * ``/api/approvals/{approval_request_id}``. Threaded from the deal-
   * room route handler when an approval is pending for this job. */
  approvalRequestId?: string | null;
  /** Server-side Job.status. Used to gate which CTAs render. */
  jobStatus?: string | null;
  /** Whether the conversation already has at least one buyer-agent
   * message. Used to decide whether to show the "Start negotiating"
   * button (when no draft AND no buyer messages, the negotiator has
   * never been kicked off) vs. the "Goti is drafting…" affordance
   * (the negotiator is in flight but the draft hasn't surfaced yet). */
  hasBuyerMessages?: boolean;
  /** Number of OTHER active sibling Jobs in the same hunt — shown in
   * the finalize-close confirmation modal so the user knows how many
   * decline messages will fan out on confirm. */
  siblingCount?: number;
}

export function NextMoveCard({
  move,
  approvalRequestId = null,
  jobStatus = null,
  hasBuyerMessages = false,
  siblingCount = 0,
}: NextMoveCardProps) {
  const router = useRouter();
  const [sendState, setSendState] = useState<
    "idle" | "submitting" | "sent" | "error"
  >("idle");
  const [sendError, setSendError] = useState<string | null>(null);
  // ``editedDraft`` is only the local buffer for the textarea in edit
  // mode. Outside edit mode, we always render the canonical
  // ``move.draft`` from the server so the UI reflects the latest
  // negotiator output without needing a sync effect.
  const [editedDraft, setEditedDraft] = useState<string>(move.draft);
  const [isEditing, setIsEditing] = useState(false);
  const sent = sendState === "sent";
  const submitting = sendState === "submitting";

  // Phase D — "Start negotiating" affordance. The negotiator no longer
  // auto-fires on Job create; we show a prominent button when:
  // - There's no draft yet (move.draft is empty), AND
  // - There are no buyer-agent messages in the conversation, AND
  // - The job isn't in a terminal state.
  // Once the user clicks, ``draftNext`` POSTs to /draft-next which
  // spawns the negotiator. We flip into a "drafting…" state and the
  // parent layout's 2s poll picks up the draft as soon as it lands.
  const noDraftYet = !move.draft || move.draft.length === 0;
  const isTerminal = jobStatus === "closed" || jobStatus === "cancelled";
  const showStartNegotiating =
    noDraftYet && !hasBuyerMessages && !isTerminal;
  const [startState, setStartState] = useState<
    "idle" | "starting" | "started" | "error"
  >("idle");
  const [startError, setStartError] = useState<string | null>(null);

  // Phase D — once the user clicks "Start negotiating", we want to
  // surface a "drafting…" message rather than the start button on the
  // next render. After that, the parent's poll loop will refresh and
  // noDraftYet may stay true briefly before the draft surfaces.
  const draftPending =
    noDraftYet && (!showStartNegotiating || startState === "started");

  // Phase F — "Ready to close" badge + finalize-close modal.
  const canFinalize =
    !!move.ready_to_close && !isTerminal && !sent && !submitting;
  const [finalizeOpen, setFinalizeOpen] = useState(false);

  const canApprove = !!approvalRequestId && !sent && !submitting;

  async function handleStartNegotiation() {
    if (!move.job_id) {
      setStartError("Missing job id.");
      setStartState("error");
      return;
    }
    setStartState("starting");
    setStartError(null);
    try {
      await draftNext(move.job_id);
      setStartState("started");
      // Trigger a parent refresh so polling picks up the new state.
      router.refresh();
    } catch (err) {
      setStartError(
        err instanceof Error
          ? err.message
          : "Couldn't start negotiating — try again.",
      );
      setStartState("error");
    }
  }

  async function handleApprove() {
    if (!approvalRequestId) {
      setSendError("No live approval — backend hasn't surfaced a draft yet.");
      setSendState("error");
      return;
    }
    setSendState("submitting");
    setSendError(null);
    try {
      const finalText = (isEditing ? editedDraft : move.draft).trim();
      await submitApprovalDecision(
        approvalRequestId,
        "approve",
        undefined,
        finalText !== (move.draft || "").trim() ? finalText : undefined,
      );
      setSendState("sent");
      // Pull fresh DealRoom so the conversation reflects the sent message
      // and the next draft (if any) shows up.
      router.refresh();
    } catch (err) {
      setSendError(
        err instanceof Error
          ? err.message
          : "Couldn't send — try again.",
      );
      setSendState("error");
    }
  }

  return (
    <aside
      className="rounded-2xl border-2 bg-paper p-5 flex flex-col gap-4 shadow-[0_4px_0_0_rgba(0,0,0,0.06)]"
      style={{ borderColor: "var(--ink-line)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-micro uppercase tracking-wider text-orange font-semibold">
            {move.headline}
          </span>
          <h2 className="text-headline font-display font-bold text-ink leading-tight">
            {move.sub}
          </h2>
        </div>
        <ReceiptIcon />
      </div>

      {/* Phase F: Ready-to-close badge. The classifier flips
          ``ready_to_close=true`` after a new buyer/seller message looks
          like it's reached agreement. Clicking opens the finalize
          modal — the user confirms the price + Goti fans out the
          decline template to siblings + closes the hunt. */}
      {canFinalize ? (
        <button
          type="button"
          onClick={() => setFinalizeOpen(true)}
          className={cn(
            "inline-flex items-center justify-center gap-2 rounded-xl py-3 px-4",
            "font-semibold border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)]",
            "bg-green text-paper hover:bg-green/95 transition",
          )}
        >
          <CheckIcon />
          Ready to close — finalize this deal
        </button>
      ) : null}

      <div className="h-px bg-ink-line/15" aria-hidden />

      <PriceLadderView ladder={move.price_ladder} />

      <p className="text-caption text-ink-2 leading-relaxed">
        {move.plain_english}
      </p>

      <SavingsReceiptView savings={move.savings} />

      <div className="flex flex-col gap-2">
        <div className="text-micro uppercase tracking-wider text-ink-3 font-semibold">
          Message to approve
        </div>
        {showStartNegotiating && startState !== "started" ? (
          <div
            className="rounded-xl bg-paper-2 px-4 py-3 text-body text-ink-2 leading-relaxed border-l-4 flex flex-col gap-3"
            style={{ borderColor: "var(--ink-line)" }}
          >
            <p>
              Goti is ready to negotiate this listing. Click below when you
              want to draft an opening message — Goti will pull BATNA leverage
              from your other active negotiations.
            </p>
            <button
              type="button"
              onClick={handleStartNegotiation}
              disabled={startState === "starting"}
              className={cn(
                "inline-flex items-center justify-center gap-2 rounded-lg bg-orange text-paper font-semibold py-2.5 px-3 border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95",
                startState === "starting" && "opacity-70 cursor-wait",
              )}
            >
              {startState === "starting" ? "Starting…" : "Start negotiating"}
            </button>
            {startError ? (
              <p className="text-caption text-accent" role="alert">
                {startError}
              </p>
            ) : null}
          </div>
        ) : draftPending ? (
          <div
            className="rounded-xl bg-paper-2 px-4 py-3 text-body text-ink-2 leading-relaxed border-l-4 border-dashed flex items-center gap-2"
            style={{ borderColor: "var(--ink-line)" }}
          >
            <span className="inline-block size-3 rounded-full bg-orange/70 animate-pulse" />
            Goti is drafting an opening message…
          </div>
        ) : isEditing ? (
          <textarea
            value={editedDraft}
            onChange={(e) => setEditedDraft(e.target.value)}
            rows={5}
            className="rounded-xl bg-paper-2 px-4 py-3 text-body text-ink leading-relaxed border-l-4 focus:outline-none focus:ring-1 focus:ring-orange/40"
            style={{ borderColor: "var(--ink-line)" }}
          />
        ) : (
          <blockquote
            className="rounded-xl bg-paper-2 px-4 py-3 text-body text-ink leading-relaxed border-l-4"
            style={{ borderColor: "var(--ink-line)" }}
          >
            <span className="font-display text-headline text-ink-3 leading-none">“</span>
            {move.draft}
          </blockquote>
        )}
      </div>

      {!showStartNegotiating && !draftPending ? (
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => {
              setIsEditing((v) => !v);
              if (!isEditing) setEditedDraft(move.draft);
            }}
            disabled={sent || submitting}
            className={cn(
              "rounded-lg bg-paper text-ink font-medium py-2.5 border border-ink-line/30",
              (sent || submitting) && "opacity-60 cursor-not-allowed",
            )}
          >
            {isEditing ? "Done editing" : "Edit"}
          </button>
          {sent ? (
            <button
              type="button"
              disabled
              className={cn(
                "inline-flex items-center justify-center gap-1.5 rounded-lg py-2.5",
                "font-semibold border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)]",
                "bg-green text-paper cursor-default",
              )}
            >
              <CheckIcon />
              Sent · just now
            </button>
          ) : (
            <button
              type="button"
              onClick={handleApprove}
              disabled={!canApprove}
              className={cn(
                "inline-flex items-center justify-center gap-1.5 rounded-lg bg-orange text-paper font-semibold py-2.5 border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95",
                !canApprove && "opacity-60 cursor-not-allowed",
              )}
            >
              {submitting ? null : <MessageIcon />}
              {submitting ? "Sending…" : "Approve & send"}
            </button>
          )}
        </div>
      ) : null}
      {sendError ? (
        <p className="text-caption text-accent" role="alert">
          {sendError}
        </p>
      ) : null}

      {sent ? (
        <Link
          href="/playbook"
          className="text-caption text-ink-3 hover:text-ink underline-offset-2 hover:underline mt-2 self-center"
        >
          View what Goti learned →
        </Link>
      ) : null}

      {/* Phase F — finalize-close modal. Mounted conditionally; the
          modal itself returns null when ``open=false``. */}
      <FinalizeCloseModal
        open={finalizeOpen}
        onClose={() => setFinalizeOpen(false)}
        jobId={move.job_id}
        suggestedClosePrice={move.suggested_close_price ?? null}
        siblingCount={siblingCount}
        signalReason={move.close_signal_reason ?? null}
      />
    </aside>
  );
}

function ReceiptIcon() {
  return (
    <span
      aria-hidden
      className="inline-flex items-center justify-center size-10 rounded-lg border bg-yellow text-ink shadow-[0_2px_0_0_rgba(0,0,0,1)]"
      style={{ borderColor: "var(--yellow-deep)" }}
    >
      <svg viewBox="0 0 16 16" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3 1.5h10v13l-2-1.2-2 1.2-2-1.2-2 1.2-2-1.2z" strokeLinejoin="round" />
        <line x1="5" y1="5" x2="11" y2="5" />
        <line x1="5" y1="8" x2="11" y2="8" />
        <line x1="5" y1="11" x2="9" y2="11" />
      </svg>
    </span>
  );
}

function MessageIcon() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M2 4h12v8H6l-3 2v-2H2z" strokeLinejoin="round" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M3 8.5l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
