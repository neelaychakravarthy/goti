"use client";

import Link from "next/link";
import { useState } from "react";

import { PriceLadderView } from "@/components/deal/price-ladder";
import { SavingsReceiptView } from "@/components/deal/savings-receipt";
import { cn } from "@/lib/utils";
import type { NextMove } from "@/types";

interface NextMoveCardProps {
  move: NextMove;
}

export function NextMoveCard({ move }: NextMoveCardProps) {
  const [sendState, setSendState] = useState<"idle" | "sent">("idle");
  const sent = sendState === "sent";

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
        <blockquote
          className="rounded-xl bg-paper-2 px-4 py-3 text-body text-ink leading-relaxed border-l-4"
          style={{ borderColor: "var(--ink-line)" }}
        >
          <span className="font-display text-headline text-ink-3 leading-none">“</span>
          {move.draft}
        </blockquote>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled
          title="Preview build"
          className="rounded-lg bg-paper text-ink font-medium py-2.5 border border-ink-line/30 opacity-60 cursor-not-allowed"
        >
          Edit
        </button>
        {sent ? (
          <button
            type="button"
            disabled
            className={cn(
              "inline-flex items-center justify-center gap-1.5 rounded-lg py-2.5",
              "font-semibold border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)]",
              "bg-green text-paper cursor-default"
            )}
          >
            <CheckIcon />
            Sent · just now
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setSendState("sent")}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-orange text-paper font-semibold py-2.5 border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95"
          >
            <MessageIcon />
            Approve &amp; send
          </button>
        )}
      </div>

      {sent ? (
        <Link
          href="/playbook"
          className="text-caption text-ink-3 hover:text-ink underline-offset-2 hover:underline mt-2 self-center"
        >
          View what Goti learned →
        </Link>
      ) : (
        <button
          type="button"
          disabled
          title="Preview build"
          className="text-caption text-ink-3 py-1 self-center opacity-60 cursor-not-allowed"
        >
          Skip this seller
        </button>
      )}
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
