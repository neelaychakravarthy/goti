"use client";

// Phase N — narrow listing card variant for inline chat use. Renders
// inside the polymorphic hunt-conversation message list when discovery
// surfaces a new candidate. Two actions:
//
// - "Start negotiation" — POSTs to /api/hunts/{id}/jobs, adds the new
//   negotiation as a tab in the hunt page's tab strip, and selects it.
// - "Open in dialog" — quick-peek via the base-ui Dialog (Phase N.4)
//   when the user wants to glance at the seller without committing.

import { useState } from "react";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { startNegotiation } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface InlineListing {
  id: string;
  title: string;
  price: number;
  marketplace: string;
  url?: string;
  image_url?: string | null;
  description?: string | null;
  location?: string | null;
  seller_name?: string | null;
}

interface Props {
  huntId: string;
  listing: InlineListing;
  targetPrice?: number | null;
  /** Called after a successful start. The page surfaces the new tab. */
  onStarted?: (jobId: string) => void;
}

export function InlineListingCard({
  huntId,
  listing,
  targetPrice,
  onStarted,
}: Props) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function handleStart() {
    if (starting) return;
    setStarting(true);
    setError(null);
    try {
      const res = await startNegotiation(
        huntId,
        listing.id,
        targetPrice ?? undefined,
      );
      onStarted?.(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start negotiation");
    } finally {
      setStarting(false);
    }
  }

  return (
    <article
      className={cn(
        "w-full max-w-[360px] rounded-2xl border bg-paper p-3 flex flex-col gap-2.5"
      )}
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <header className="flex items-baseline justify-between gap-2">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
          {marketplaceLabel(listing.marketplace)} candidate
        </span>
        {listing.location ? (
          <span className="text-micro text-ink-3">{listing.location}</span>
        ) : null}
      </header>

      {listing.image_url ? (
        // External urls in <Image> need the host allowlist in next.config.
        // Fall back to plain <img> to avoid breaking deploys with unknown hosts.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={listing.image_url}
          alt={listing.title}
          className="w-full h-32 object-cover rounded-xl border"
          style={{ borderColor: "rgba(15,15,15,0.08)" }}
        />
      ) : null}

      <h3 className="font-display font-bold text-ink text-body leading-tight">
        {listing.title}
      </h3>

      <div className="flex items-baseline gap-2">
        <span className="font-display font-bold text-ink text-headline">
          ${Math.round(listing.price)}
        </span>
        {typeof targetPrice === "number" ? (
          <span className="text-micro text-ink-3">
            target ${Math.round(targetPrice)}
          </span>
        ) : null}
      </div>

      {listing.description ? (
        <p className="text-caption text-ink-2 line-clamp-2">
          {listing.description}
        </p>
      ) : null}

      <div className="flex flex-col gap-1.5 mt-1">
        <button
          type="button"
          onClick={handleStart}
          disabled={starting}
          className={cn(
            "rounded-2xl border bg-orange px-3 py-1.5 text-caption font-semibold text-paper",
            "shadow-[0_2px_0_0_rgba(0,0,0,1)]",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
          style={{ borderColor: "rgba(15,15,15,0.5)" }}
        >
          {starting ? "Starting…" : "Start negotiation"}
        </button>
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className={cn(
            "rounded-2xl border bg-paper px-3 py-1.5 text-caption font-medium text-ink hover:bg-paper-3",
            "shadow-[0_2px_0_0_rgba(0,0,0,1)]"
          )}
          style={{ borderColor: "rgba(15,15,15,0.12)" }}
        >
          Open in dialog
        </button>
      </div>

      {error ? (
        <p className="text-micro text-orange mt-1">{error}</p>
      ) : null}

      <Dialog
        open={dialogOpen}
        onOpenChange={(v: boolean) => setDialogOpen(v)}
      >
        <DialogContent className="max-w-[640px]">
          <DialogTitle>{listing.title}</DialogTitle>
          <div className="flex flex-col gap-2">
            {listing.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={listing.image_url}
                alt={listing.title}
                className="w-full h-48 object-cover rounded-xl border"
                style={{ borderColor: "rgba(15,15,15,0.08)" }}
              />
            ) : null}
            <p className="text-caption text-ink-2">
              {listing.description || "No description provided."}
            </p>
            <div className="flex items-baseline gap-3">
              <span className="font-display font-bold text-ink text-headline">
                ${Math.round(listing.price)}
              </span>
              <span className="text-micro text-ink-3">
                {marketplaceLabel(listing.marketplace)}
              </span>
              {listing.location ? (
                <span className="text-micro text-ink-3">
                  · {listing.location}
                </span>
              ) : null}
            </div>
            {listing.url ? (
              <a
                href={listing.url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-micro text-ink-2 underline-offset-2 hover:underline"
              >
                Open original listing →
              </a>
            ) : null}
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDialogOpen(false)}
              className={cn(
                "rounded-2xl border bg-paper px-3 py-1.5 text-caption font-medium text-ink",
                "shadow-[0_2px_0_0_rgba(0,0,0,1)]"
              )}
              style={{ borderColor: "rgba(15,15,15,0.12)" }}
            >
              Close
            </button>
            <button
              type="button"
              onClick={async () => {
                setDialogOpen(false);
                await handleStart();
              }}
              disabled={starting}
              className={cn(
                "rounded-2xl border bg-orange px-3 py-1.5 text-caption font-semibold text-paper",
                "shadow-[0_2px_0_0_rgba(0,0,0,1)]"
              )}
              style={{ borderColor: "rgba(15,15,15,0.5)" }}
            >
              Start negotiation
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </article>
  );
}

function marketplaceLabel(m: string): string {
  switch (m) {
    case "fb":
    case "facebook":
      return "Facebook";
    case "nextdoor":
      return "Nextdoor";
    case "offerup":
      return "OfferUp";
    case "craigslist":
      return "Craigslist";
    default:
      return m;
  }
}
