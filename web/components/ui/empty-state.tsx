"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title: string;
  body?: string;
  action?: ReactNode;
  className?: string;
}

/**
 * Shared empty-state component for pages that have nothing to show yet
 * (no hunts, no approvals, no playbook cases, etc.). Matches the
 * paper-base palette.
 */
export function EmptyState({ title, body, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-ink-line/15 bg-paper-2 px-6 py-8 flex flex-col items-center text-center gap-3",
        className,
      )}
    >
      <h3 className="font-display font-semibold text-body-lg text-ink">{title}</h3>
      {body ? (
        <p className="text-body text-ink-2 max-w-[480px]">{body}</p>
      ) : null}
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  );
}
