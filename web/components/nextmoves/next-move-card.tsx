import Link from "next/link";

import { cn } from "@/lib/utils";
import type { NextMoveItem, NextMoveKind } from "@/types";

interface NextMoveCardProps {
  item: NextMoveItem;
  className?: string;
}

interface KindStyle {
  badgeLabel: string;
  badgeClass: string;
  cardClass: string;
  actionClass?: string;
  showLeftAccent?: boolean;
}

const KIND: Record<NextMoveKind, KindStyle> = {
  discovery_update: {
    badgeLabel: "Discovery",
    badgeClass: "bg-panel-dark text-paper",
    cardClass: "bg-paper-2 border-ink-line/20",
  },
  question: {
    badgeLabel: "Question",
    badgeClass: "bg-panel-dark text-paper",
    cardClass: "bg-paper border-ink-line/20",
    showLeftAccent: true,
  },
  recommendation: {
    badgeLabel: "Recommendation",
    badgeClass: "bg-panel-dark text-paper",
    cardClass: "bg-paper-2 border-ink-line/20",
  },
  approval: {
    badgeLabel: "Needs approval",
    badgeClass: "bg-orange text-paper border border-ink-line",
    cardClass: "bg-orange-soft border-orange/40",
    actionClass:
      "bg-orange text-paper border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95",
  },
  seller_reply: {
    badgeLabel: "Reply",
    badgeClass: "bg-green text-paper",
    cardClass: "bg-green-soft border-green/30",
    actionClass:
      "bg-green text-paper border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-green/95",
  },
  risk_check: {
    badgeLabel: "Risk check",
    badgeClass: "bg-yellow text-ink border border-yellow-deep",
    cardClass: "bg-yellow-soft border-yellow-deep/40",
  },
  better_offer: {
    badgeLabel: "Better offer",
    badgeClass: "bg-yellow text-ink border border-yellow-deep",
    cardClass: "bg-yellow-soft border-yellow-deep/40",
    actionClass:
      "bg-orange text-paper border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95",
  },
  close: {
    badgeLabel: "Close",
    badgeClass: "bg-green text-paper",
    cardClass: "bg-green-soft border-green/30",
    actionClass:
      "bg-green text-paper border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-green/95",
  },
};

export function NextMoveCard({ item, className }: NextMoveCardProps) {
  const style = KIND[item.kind];
  const accent =
    style.showLeftAccent && "border-l-4 border-l-orange";

  return (
    <article
      className={cn(
        "rounded-xl border p-3.5 flex flex-col gap-2",
        style.cardClass,
        accent,
        className
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className={cn(
            "inline-flex items-center rounded-full px-2 py-0.5 text-micro font-medium",
            style.badgeClass
          )}
        >
          {style.badgeLabel}
        </span>
        {item.timestamp ? (
          <span className="text-micro text-ink-3">{item.timestamp}</span>
        ) : null}
      </div>

      <h3 className="text-body font-display font-semibold text-ink leading-snug">
        {item.title}
      </h3>

      <p className="text-caption text-ink-2 leading-relaxed">{item.body}</p>

      {item.action_label ? (
        item.action_href ? (
          <Link
            href={item.action_href}
            className={cn(
              "mt-1 inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-caption font-semibold transition w-fit",
              style.actionClass ??
                "bg-paper text-ink border border-ink-line/30 hover:bg-paper-3"
            )}
          >
            {item.action_label}
            <span aria-hidden>→</span>
          </Link>
        ) : (
          <button
            type="button"
            className={cn(
              "mt-1 inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-caption font-semibold transition w-fit",
              style.actionClass ??
                "bg-paper text-ink border border-ink-line/30 hover:bg-paper-3"
            )}
          >
            {item.action_label}
          </button>
        )
      ) : null}
    </article>
  );
}
