"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { MarketplacePhoto } from "@/components/marketplace/marketplace-photo";
import { DiscoveryStatusLine } from "@/components/search/discovery-status-line";
import { PriceTag } from "@/components/ui/price-tag";
import { cn, marketplaceLabel } from "@/lib/utils";
import type { DiscoveryStage, Listing } from "@/types";

interface DiscoveryFeedProps {
  listings: Listing[];
  stages: DiscoveryStage[];
  /** When set, the "Review options" CTA links here. When undefined, renders disabled. */
  reviewHref?: string;
}

export function DiscoveryFeed({ listings, stages, reviewHref }: DiscoveryFeedProps) {
  const [now, setNow] = useState(0);

  useEffect(() => {
    const start = Date.now();
    let raf = 0;
    let cancelled = false;
    function tick() {
      if (cancelled) return;
      setNow(Date.now() - start);
      raf = window.setTimeout(tick, 120) as unknown as number;
    }
    tick();
    return () => {
      cancelled = true;
      window.clearTimeout(raf);
    };
  }, []);

  // Cap time at the final stage so the panel settles rather than running forever.
  const lastStageT = stages[stages.length - 1]?.t_ms ?? 0;
  const clamped = Math.min(now, lastStageT);
  const done = now >= lastStageT;

  const currentStage = useMemo(() => {
    let active = stages[0];
    for (const s of stages) {
      if (clamped >= s.t_ms) active = s;
    }
    return active;
  }, [clamped, stages]);

  const visibleListings = useMemo(() => {
    const ids = new Set<string>();
    for (const s of stages) {
      if (clamped >= s.t_ms && s.appears_listing_id) {
        ids.add(s.appears_listing_id);
      }
    }
    return listings.filter((l) => ids.has(l.id));
  }, [clamped, listings, stages]);

  const skeletonCount = Math.max(0, listings.length - visibleListings.length);

  return (
    <div className="flex flex-col gap-4">
      <DiscoveryStatusLine text={currentStage?.status_text ?? ""} done={done} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {visibleListings.map((l) => (
          <DiscoveredCard key={l.id} listing={l} />
        ))}
        {Array.from({ length: skeletonCount }).map((_, i) => (
          <SkeletonCard key={`sk-${i}`} />
        ))}
      </div>

      {done ? (
        <div className="flex items-center justify-end pt-2">
          {reviewHref ? (
            <Link
              href={reviewHref}
              className={cn(
                "inline-flex items-center gap-2 rounded-xl bg-orange px-5 py-3 text-paper font-semibold",
                "border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95 transition"
              )}
            >
              Review options
              <span aria-hidden>→</span>
            </Link>
          ) : (
            <button
              type="button"
              disabled
              title="Preview build"
              className={cn(
                "inline-flex items-center gap-2 rounded-xl bg-orange px-5 py-3 text-paper font-semibold",
                "border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] opacity-60 cursor-not-allowed"
              )}
            >
              Review options
              <span aria-hidden>→</span>
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}

function DiscoveredCard({ listing }: { listing: Listing }) {
  return (
    <article
      className="goti-card-in rounded-2xl border bg-paper p-3 flex flex-col gap-2.5"
      style={{ borderColor: "rgba(15,15,15,0.18)" }}
    >
      <MarketplacePhoto
        listingId={listing.id}
        marketplace={listing.marketplace}
        size="sm"
        showThumbs={false}
      />
      <div className="flex items-start justify-between gap-2">
        <h4 className="text-caption font-display font-semibold text-ink leading-tight">
          {listing.title}
        </h4>
        <PriceTag amount={listing.asking_price} size="sm" rotate={-1} />
      </div>
      <dl className="text-micro text-ink-2 flex flex-col gap-0.5">
        <div className="flex items-center gap-1.5">
          <dt className="text-ink-3">Likely close</dt>
          <dd className="text-ink font-semibold">${listing.likely_close}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="text-ink-3">Seller</dt>
          <dd className="text-ink-2">{listing.seller.name}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="text-ink-3">Where</dt>
          <dd className="text-ink-2">
            {listing.location_label}
            {listing.distance_mi ? ` · ${listing.distance_mi} mi` : ""}
          </dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="text-ink-3">Posted</dt>
          <dd className="text-ink-2">
            {listing.posted_age_days} day
            {listing.posted_age_days === 1 ? "" : "s"} ago
          </dd>
        </div>
      </dl>
      <div className="text-micro text-ink-3 italic">
        found via {marketplaceLabel(listing.marketplace)}
      </div>
    </article>
  );
}

function SkeletonCard() {
  return (
    <div
      className="rounded-2xl border bg-paper-2 p-3 flex flex-col gap-2.5 h-[240px]"
      style={{ borderColor: "rgba(15,15,15,0.08)" }}
    >
      <div className="goti-shimmer rounded-lg h-32 w-full" />
      <div className="goti-shimmer rounded-md h-3 w-3/4" />
      <div className="goti-shimmer rounded-md h-3 w-1/2" />
      <div className="goti-shimmer rounded-md h-3 w-2/3" />
    </div>
  );
}
