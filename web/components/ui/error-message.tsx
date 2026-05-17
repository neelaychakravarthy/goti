"use client";

import { cn } from "@/lib/utils";

interface ErrorMessageProps {
  title?: string;
  /** Friendly user-facing message; never raw stack traces. */
  body?: string;
  /** Optional retry handler — surfaces a "Retry" button. */
  onRetry?: () => void;
  className?: string;
}

/**
 * Shared error-state component. Friendly message + optional retry — no
 * stack traces leaked to the user.
 */
export function ErrorMessage({
  title = "Something went wrong",
  body = "Goti couldn't load this view. Try again in a moment.",
  onRetry,
  className,
}: ErrorMessageProps) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-2xl border border-ink-line/15 bg-paper-2 px-6 py-6 flex flex-col gap-3 items-start",
        className,
      )}
    >
      <h3 className="font-display font-semibold text-body-lg text-ink">{title}</h3>
      <p className="text-body text-ink-2">{body}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-2 rounded-xl bg-orange px-4 py-2 text-paper text-caption font-semibold border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95 transition"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
