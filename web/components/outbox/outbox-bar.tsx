import Link from "next/link";

import { cn } from "@/lib/utils";
import type { Outbox } from "@/types";

interface OutboxBarProps {
  outbox: Outbox;
  className?: string;
}

/**
 * Persistent thin strip showing outbox counts. Links to /approve.
 * "Outbox: 0 sent · 3 drafts · 3 waiting for your approval"
 */
export function OutboxBar({ outbox, className }: OutboxBarProps) {
  return (
    <div
      className={cn(
        "w-full border-b bg-paper-2",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.06)" }}
    >
      <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-4 px-6 py-2 text-caption text-ink-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium text-ink">Outbox:</span>
          <span>
            <strong className="text-ink font-semibold">{outbox.sent}</strong> sent
            <span className="mx-1.5 text-ink-3">·</span>
            <strong className="text-ink font-semibold">{outbox.drafts}</strong> drafts
            <span className="mx-1.5 text-ink-3">·</span>
            <strong className="text-orange font-semibold">
              {outbox.waiting}
            </strong>{" "}
            waiting for your approval
          </span>
        </div>
        <Link
          href="/approve"
          className="shrink-0 text-orange font-medium hover:underline"
        >
          Review next moves →
        </Link>
      </div>
    </div>
  );
}
