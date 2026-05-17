"use client";

// Phase F of the ancient-brewing-brooks plan.
//
// Confirmation modal that opens when the user clicks the "Ready to
// close" badge on the deal page. Surface:
// - Suggested close price (from the classifier verdict) — editable.
// - Optional custom yes-message (defaults to a sensible canned one
//   on the server when left blank).
// - Plain-language warning about the sibling decline fan-out.
//
// On confirm: POST /api/jobs/{job_id}/finalize-close with
// {final_price, agreed_text}. Closes the modal + router.refresh() on
// success so the deal page re-renders with the closed state.

import { useState } from "react";
import { useRouter } from "next/navigation";

import { finalizeClose } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface FinalizeCloseModalProps {
  open: boolean;
  onClose: () => void;
  jobId: string;
  /** Server-provided suggested close price (from the classifier).
   * Used as the default input value; user can override. */
  suggestedClosePrice?: number | null;
  /** Number of sibling jobs in the same hunt that will receive the
   * hardcoded decline template on confirm. Surfaced in the warning
   * line so the user knows what they're committing to. */
  siblingCount?: number;
  /** Optional reason string from the classifier — shown above the
   * inputs so the user knows why Goti thinks this is ready to close. */
  signalReason?: string | null;
}

export function FinalizeCloseModal({
  open,
  onClose,
  jobId,
  suggestedClosePrice = null,
  siblingCount = 0,
  signalReason = null,
}: FinalizeCloseModalProps) {
  const router = useRouter();
  const [priceInput, setPriceInput] = useState<string>(
    suggestedClosePrice ? String(Math.round(suggestedClosePrice)) : "",
  );
  const [agreedText, setAgreedText] = useState<string>("");
  const [state, setState] = useState<"idle" | "submitting" | "closed" | "error">(
    "idle",
  );
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!open) return null;

  async function onConfirm() {
    const parsed = Number.parseFloat(priceInput.replace(/[^0-9.]/g, ""));
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setErrorMsg("Enter a positive final price.");
      setState("error");
      return;
    }
    setState("submitting");
    setErrorMsg(null);
    try {
      await finalizeClose(jobId, parsed, agreedText.trim() || undefined);
      setState("closed");
      // Pull a fresh deal-page snapshot so the closed status renders.
      router.refresh();
      // Auto-close after the parent has a tick to re-render.
      setTimeout(() => {
        onClose();
      }, 600);
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : "Couldn't close — try again.",
      );
      setState("error");
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Finalize deal close"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4"
      onClick={(e) => {
        // Click-outside closes — but not while a submit is in flight.
        if (e.target === e.currentTarget && state !== "submitting") onClose();
      }}
    >
      <div
        className="w-full max-w-md rounded-2xl border-2 bg-paper p-5 shadow-[0_6px_0_0_rgba(0,0,0,0.1)] flex flex-col gap-4"
        style={{ borderColor: "var(--ink-line)" }}
      >
        <div className="flex flex-col gap-1">
          <span className="text-micro uppercase tracking-wider text-green font-semibold">
            Ready to close
          </span>
          <h2 className="text-headline font-display font-bold text-ink leading-tight">
            Confirm the final price.
          </h2>
          {signalReason ? (
            <p className="text-caption text-ink-2 leading-snug mt-1">
              {signalReason}
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <label
            htmlFor={`finalize-price-${jobId}`}
            className="text-micro uppercase tracking-wider text-ink-3 font-semibold"
          >
            Final price (USD)
          </label>
          <input
            id={`finalize-price-${jobId}`}
            type="text"
            inputMode="decimal"
            autoFocus
            placeholder="e.g. 195"
            value={priceInput}
            onChange={(e) => setPriceInput(e.target.value)}
            disabled={state === "submitting" || state === "closed"}
            className="rounded-md border border-ink-line/40 bg-paper-2 px-3 py-2 text-body text-ink focus:outline-none focus:ring-2 focus:ring-green/40"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label
            htmlFor={`finalize-text-${jobId}`}
            className="text-micro uppercase tracking-wider text-ink-3 font-semibold"
          >
            Yes-message <span className="text-ink-3 normal-case">(optional)</span>
          </label>
          <textarea
            id={`finalize-text-${jobId}`}
            value={agreedText}
            onChange={(e) => setAgreedText(e.target.value)}
            placeholder="Leave blank to send Goti's default confirmation."
            rows={3}
            disabled={state === "submitting" || state === "closed"}
            className="rounded-md border border-ink-line/40 bg-paper-2 px-3 py-2 text-body text-ink leading-relaxed focus:outline-none focus:ring-2 focus:ring-green/40"
          />
        </div>

        {siblingCount > 0 ? (
          <div className="rounded-lg border border-ink-line/30 bg-yellow/20 px-3 py-2 text-caption text-ink leading-relaxed">
            This will send a polite decline to{" "}
            <strong>
              {siblingCount} other seller{siblingCount === 1 ? "" : "s"}
            </strong>{" "}
            in this hunt and close the hunt.
          </div>
        ) : (
          <div className="rounded-lg border border-ink-line/30 bg-paper-2 px-3 py-2 text-caption text-ink-2 leading-relaxed">
            This will close this deal and the parent hunt. No other sellers to
            decline.
          </div>
        )}

        {errorMsg ? (
          <p className="text-caption text-accent" role="alert">
            {errorMsg}
          </p>
        ) : null}

        <div className="grid grid-cols-2 gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={state === "submitting"}
            className={cn(
              "rounded-lg bg-paper text-ink font-medium py-2.5 border border-ink-line/30",
              state === "submitting" && "opacity-60 cursor-not-allowed",
            )}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={state === "submitting" || state === "closed"}
            className={cn(
              "inline-flex items-center justify-center gap-1.5 rounded-lg py-2.5",
              "font-semibold border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)]",
              state === "closed"
                ? "bg-green text-paper"
                : "bg-green text-paper hover:bg-green/95",
              (state === "submitting" || state === "closed") && "opacity-90",
            )}
          >
            {state === "submitting"
              ? "Closing…"
              : state === "closed"
                ? "Deal closed"
                : "Confirm close"}
          </button>
        </div>
      </div>
    </div>
  );
}
