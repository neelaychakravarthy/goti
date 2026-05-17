"use client";

// Phase N — narrow approval card variant for inline chat use. Rendered
// when a hunt-scoped approval (clarifying question, picker pause, etc.)
// surfaces from the conversation stream. For job-bound approvals the
// user navigates to the right negotiation tab instead.

import Link from "next/link";

import { cn } from "@/lib/utils";

interface Props {
  title: string;
  body?: string;
  targetHref: string;
  className?: string;
}

export function InlineApprovalCard({
  title,
  body,
  targetHref,
  className,
}: Props) {
  return (
    <article
      className={cn(
        "w-full max-w-[360px] rounded-2xl border bg-yellow/30 border-yellow-deep/50 p-3 flex flex-col gap-2",
        className
      )}
    >
      <header className="flex items-baseline justify-between gap-2">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
          Needs your input
        </span>
      </header>
      <h3 className="font-display font-bold text-ink text-body leading-tight">
        {title}
      </h3>
      {body ? (
        <p className="text-caption text-ink-2 leading-relaxed">{body}</p>
      ) : null}
      <Link
        href={targetHref}
        className={cn(
          "self-start rounded-2xl border bg-orange px-3 py-1.5 text-caption font-semibold text-paper",
          "shadow-[0_2px_0_0_rgba(0,0,0,1)]"
        )}
        style={{ borderColor: "rgba(15,15,15,0.5)" }}
      >
        Resolve →
      </Link>
    </article>
  );
}
