"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import type { HuntKey } from "@/lib/hunts";
import { cn } from "@/lib/utils";

interface SelectionSummaryBarProps {
  count: number;
  selectedTitles: string[];
  projectedSavings: string;
  /** Where the orange CTA navigates on click. */
  href?: string;
  /** Active hunt. Non-desk hunts hide the bar (preview build). */
  huntKey?: HuntKey;
}

export function SelectionSummaryBar({
  count,
  selectedTitles,
  projectedSavings,
  href = "/approve",
  huntKey = "standing-desk",
}: SelectionSummaryBarProps) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  if (count === 0) return null;
  if (huntKey !== "standing-desk") return null;

  const titles =
    selectedTitles.length === 0
      ? ""
      : ` · Drafts will be prepared for: ${selectedTitles.join(", ")}`;

  return (
    <div
      className="sticky bottom-0 left-0 right-0 z-20 border-t bg-paper-2/95 backdrop-blur"
      style={{ borderColor: "rgba(15,15,15,0.18)" }}
    >
      <div className="mx-auto max-w-[1200px] flex flex-wrap items-center justify-between gap-3 px-6 py-3">
        <div className="text-caption text-ink-2 min-w-0">
          <span className="text-ink font-semibold">{count} selected</span>
          <span className="text-ink-3">{titles}</span>
          <span className="mx-2 text-ink-3">·</span>
          <span>
            projected savings{" "}
            <span className="text-ink font-semibold">{projectedSavings}</span>
          </span>
        </div>

        <button
          type="button"
          disabled={pending}
          onClick={() =>
            startTransition(() => {
              router.push(href);
            })
          }
          className={cn(
            "inline-flex items-center gap-2 rounded-xl bg-orange px-5 py-2.5 text-paper font-semibold",
            "border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95 transition",
            "disabled:opacity-60"
          )}
        >
          Draft messages for selected products
          <span aria-hidden>→</span>
        </button>
      </div>
    </div>
  );
}
