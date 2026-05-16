"use client";

import { MarketplacePhoto } from "@/components/marketplace/marketplace-photo";
import { PriceTag } from "@/components/ui/price-tag";
import { RankingPill } from "@/components/ui/ranking-pill";
import { StatusChip } from "@/components/ui/status-chip";
import { TrustBadge } from "@/components/ui/trust-badge";
import { cn, marketplaceLabel } from "@/lib/utils";
import type { Listing } from "@/types";

interface ProductResultCardProps {
  listing: Listing;
  rank: number;
  selected: boolean;
  onToggle: (id: string) => void;
}

export function ProductResultCard({
  listing,
  rank,
  selected,
  onToggle,
}: ProductResultCardProps) {
  return (
    <article
      className={cn(
        "relative rounded-2xl border bg-paper-2 p-4 flex gap-4 transition",
        selected
          ? "border-orange ring-1 ring-orange/50"
          : "border-ink-line/20"
      )}
    >
      {/* Top-right selection checkbox — canonical control for "pursue this". */}
      <button
        type="button"
        role="checkbox"
        aria-checked={selected}
        aria-label={
          selected
            ? `Deselect ${listing.title}`
            : `Select ${listing.title} to pursue`
        }
        onClick={() => onToggle(listing.id)}
        className={cn(
          "absolute top-3 right-3 inline-flex items-center justify-center size-6 rounded-md border transition",
          selected
            ? "bg-orange border-ink-line text-paper shadow-[0_2px_0_0_rgba(0,0,0,1)]"
            : "bg-paper border-ink-line/60 hover:border-ink-line"
        )}
      >
        {selected ? (
          <svg
            aria-hidden
            viewBox="0 0 12 12"
            className="size-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
          >
            <path
              d="M2 6.5L5 9.5L10 3.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : null}
      </button>

      <div className="w-[40%] shrink-0">
        <MarketplacePhoto
          listingId={listing.id}
          marketplace={listing.marketplace}
          size="md"
        />
      </div>

      <div className="flex-1 flex flex-col min-w-0 gap-2.5 pr-8">
        <div className="flex items-start justify-between gap-3">
          <RankingPill rank={rank} label={listing.rank_label} />
          <PriceTag amount={listing.asking_price} size="sm" rotate={-1} />
        </div>

        {selected ? (
          <span
            className="inline-flex w-fit items-center gap-1 rounded-full bg-orange-soft px-2 py-0.5 text-micro font-semibold text-orange border border-orange/40"
          >
            Selected to pursue
          </span>
        ) : null}

        <h3 className="text-headline font-display font-semibold text-ink leading-tight">
          {listing.title}
        </h3>

        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-caption text-ink-2">
          <Meta label="Marketplace" value={marketplaceLabel(listing.marketplace)} />
          <Meta label="Likely close" value={`$${listing.likely_close}`} accent />
          <Meta
            label="Seller"
            value={`${listing.seller.name}${listing.seller.sales ? ` · ${listing.seller.sales} sales` : ""}`}
          />
          <Meta
            label="Distance"
            value={`${listing.location_label}${listing.distance_mi ? ` · ${listing.distance_mi} mi` : ""}`}
          />
          <Meta
            label="Posted"
            value={`${listing.posted_age_days} day${listing.posted_age_days === 1 ? "" : "s"} ago`}
          />
          <Meta label="Pickup" value={listing.pickup_constraint} />
        </dl>

        <div
          className="rounded-lg border bg-paper px-3 py-2"
          style={{ borderColor: "rgba(15,15,15,0.1)" }}
        >
          <div className="text-micro uppercase tracking-wider font-semibold text-ink-3">
            Why Goti ranked it here
          </div>
          <p className="text-caption text-ink mt-0.5">{listing.why_ranked}</p>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {listing.seller.verified ? (
            <TrustBadge variant="verified">Verified neighbor</TrustBadge>
          ) : null}
          {listing.seller.rating ? (
            <TrustBadge variant="rating">{listing.seller.rating}★</TrustBadge>
          ) : null}
          {listing.seller.reply_speed ? (
            <StatusChip tone="neutral">{listing.seller.reply_speed}</StatusChip>
          ) : null}
          <StatusChip tone="neutral">{listing.condition}</StatusChip>
          {listing.note ? (
            <StatusChip tone="neutral">{listing.note}</StatusChip>
          ) : null}
        </div>

        <div className="pt-1 mt-auto">
          <button
            type="button"
            onClick={() => onToggle(listing.id)}
            className={cn(
              "inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-caption font-semibold transition w-full md:w-auto",
              selected
                ? "bg-orange text-paper border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95"
                : "bg-paper text-ink border border-ink-line/30 hover:bg-paper-3"
            )}
          >
            {selected ? (
              <>
                Pursue this
                <span aria-hidden>✓</span>
              </>
            ) : (
              <>
                Select to pursue
                <span aria-hidden>+</span>
              </>
            )}
          </button>
        </div>
      </div>
    </article>
  );
}

function Meta({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex flex-col">
      <dt className="text-micro text-ink-3 font-medium">{label}</dt>
      <dd
        className={
          accent
            ? "text-caption text-ink font-semibold"
            : "text-caption text-ink-2"
        }
      >
        {value}
      </dd>
    </div>
  );
}
