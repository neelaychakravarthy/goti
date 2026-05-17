"use client";

import { cn } from "@/lib/utils";

interface LoadingSpinnerProps {
  /** Optional label rendered beside the spinner (e.g. "Searching marketplaces…"). */
  label?: string;
  /** Wrapping container className. */
  className?: string;
  /** Spinner pixel size (default 24). */
  size?: number;
}

/**
 * Inline spinner shared across async data-fetch pages. Matches the
 * paper-base palette so it sits comfortably inside any panel.
 */
export function LoadingSpinner({
  label,
  className,
  size = 24,
}: LoadingSpinnerProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 text-ink-2 text-body",
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <span
        className="inline-block animate-spin rounded-full border-2 border-ink-line/40 border-t-ink"
        style={{ width: size, height: size }}
        aria-hidden
      />
      {label ? <span>{label}</span> : null}
    </div>
  );
}
