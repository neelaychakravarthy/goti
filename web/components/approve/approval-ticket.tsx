import Link from "next/link";

import { MarketplaceBadge } from "@/components/marketplace/marketplace-badge";
import { ProductThumb } from "@/components/approve/product-thumb";
import { PriceTag } from "@/components/ui/price-tag";
import { StatusChip } from "@/components/ui/status-chip";
import { cn } from "@/lib/utils";
import type { ApprovalTicket } from "@/types";

interface ApprovalTicketCardProps {
  ticket: ApprovalTicket;
}

function statusChipFor(status: ApprovalTicket["status"]) {
  switch (status) {
    case "waiting":
      return { tone: "waiting" as const, label: "Waiting for approval" };
    case "selected":
      return { tone: "selected" as const, label: "Selected" };
    case "needs_edit":
      return { tone: "needs_edit" as const, label: "Needs edit" };
    case "lower_priority":
      return { tone: "lower_priority" as const, label: "Lower priority" };
  }
}

// Only j-uplift and j-flexispot have wired deal rooms today. Other approval
// tickets (ap-vari, ap-jarvis, etc.) get the disabled treatment.
const REAL_DEAL_ROOMS = new Set(["j-uplift", "j-flexispot"]);

export function ApprovalTicketCard({ ticket }: ApprovalTicketCardProps) {
  const chip = statusChipFor(ticket.status);
  // Approval ids mirror the listing ids (ap-foo ↔ l-foo) for the round-1 demo.
  const thumbListingId = ticket.id.replace(/^ap-/, "l-");
  const dealId = ticket.id.replace(/^ap-/, "j-");
  const dealExists = REAL_DEAL_ROOMS.has(dealId);

  return (
    <article
      className={cn(
        "rounded-2xl border bg-paper p-4",
        ticket.selected
          ? "border-orange ring-1 ring-orange/40"
          : "border-ink-line/20"
      )}
    >
      <header className="flex items-center justify-between gap-3 mb-3">
        <StatusChip tone={chip.tone}>{chip.label}</StatusChip>
        <StatusChip tone="draft_saved">Draft saved · not sent</StatusChip>
      </header>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-3 flex flex-col gap-2">
          <div className="flex items-start gap-3">
            <ProductThumb
              listingId={thumbListingId}
              size={48}
              alt={ticket.listing_title}
            />
            <div className="flex flex-col min-w-0">
              <div className="text-micro uppercase tracking-wider text-ink-3 font-medium">
                To
              </div>
              <div className="text-body font-semibold text-ink leading-tight">
                {ticket.recipient_name}
              </div>
            </div>
          </div>
          <MarketplaceBadge marketplace={ticket.marketplace} size="sm" />
          <div className="text-caption text-ink-2 mt-1">
            {ticket.listing_title}
          </div>
          <div className="pt-1">
            <PriceTag amount={ticket.ask_price} size="sm" rotate={-2} />
          </div>
        </div>

        <div className="col-span-12 md:col-span-6 flex flex-col gap-2">
          <div className="text-micro uppercase tracking-wider text-ink-3 font-medium">
            Draft message
          </div>
          <blockquote
            className="rounded-xl bg-paper-2 px-4 py-3 text-body text-ink leading-relaxed border-l-4"
            style={{ borderColor: "var(--ink-line)" }}
          >
            <span className="font-display text-headline text-ink-3 leading-none">“</span>
            {ticket.draft_text}
          </blockquote>
          <div className="text-caption text-ink-2">
            <strong className="font-semibold text-ink">Why: </strong>
            {ticket.why_text}
          </div>
        </div>

        <div className="col-span-12 md:col-span-3 flex flex-col gap-2">
          <div className="text-micro uppercase tracking-wider text-ink-3 font-medium">
            Expected outcome
          </div>
          <div className="rounded-lg border border-ink-line/15 bg-paper-2/70 px-3 py-2 text-caption text-ink">
            {ticket.expected_outcome}
          </div>

          {dealExists ? (
            <Link
              href={`/deal/${dealId}`}
              className="text-caption text-ink-3 hover:text-ink underline-offset-2 hover:underline self-start"
            >
              View conversation →
            </Link>
          ) : (
            <span
              className="text-caption text-ink-3 opacity-60 cursor-not-allowed self-start"
              title="Preview build"
            >
              View conversation →
            </span>
          )}

          <div className="flex flex-col gap-1.5 mt-1">
            {dealExists ? (
              <Link
                href={`/deal/${dealId}`}
                className="text-center rounded-lg bg-orange text-paper font-semibold py-2 border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95"
              >
                Approve
              </Link>
            ) : (
              <button
                type="button"
                disabled
                title="Preview build"
                className="text-center rounded-lg bg-orange text-paper font-semibold py-2 border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] opacity-60 cursor-not-allowed"
              >
                Approve
              </button>
            )}
            <button
              type="button"
              disabled
              title="Preview build"
              className="rounded-lg bg-paper text-ink font-medium py-2 border border-ink-line/30 opacity-60 cursor-not-allowed"
            >
              Edit
            </button>
            <button
              type="button"
              disabled
              title="Preview build"
              className="text-caption text-ink-3 py-1 opacity-60 cursor-not-allowed"
            >
              Skip
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}
