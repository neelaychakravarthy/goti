"use client";

// Right-side Candidates panel — discovered listings for the current
// hunt. Lives next to the chat (collapsible) instead of inline in the
// conversation, because discovery + negotiations happen in parallel
// and don't fit a sequential chat layout.
//
// Source: GET /api/hunts/<id>/listings — same endpoint the inline
// cards used. Polls every 5s + refreshes on every notification-stream
// event so newly-discovered candidates appear in near-real-time.

import { useEffect, useMemo, useState } from "react";

import { getHuntListings, startNegotiation, type HuntListingEntry } from "@/lib/api-client";
import { useNotifications } from "@/lib/notifications-context";
import { cn } from "@/lib/utils";

interface Props {
  huntId: string;
  /** Fired after a candidate's "Start negotiation" succeeds — parent
   *  opens the seller-conversation slideover. */
  onStarted: (jobId: string) => void;
  className?: string;
}

export function CandidatesPanel({ huntId, onStarted, className }: Props) {
  const [listings, setListings] = useState<HuntListingEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const { notifications } = useNotifications();
  const notifCount = notifications.length;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const ls = await getHuntListings(huntId);
        if (!cancelled) {
          setListings(ls);
          setLoaded(true);
        }
      } catch {
        if (!cancelled) setLoaded(true);
      }
    }
    load();
    const id = setInterval(load, 5_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [huntId, notifCount]);

  // Split into discovered (no Job yet — actionable) + accepted (Job
  // started — view-only here; the slideover handles the rest). Sort
  // discovered by recency-ish — listings.sort isn't strict but the
  // backend returns them oldest-first so we just reverse.
  const { discovered, accepted } = useMemo(() => {
    const disc: HuntListingEntry[] = [];
    const acc: HuntListingEntry[] = [];
    for (const l of listings) {
      if (l.job_id) acc.push(l);
      else disc.push(l);
    }
    return { discovered: disc.reverse(), accepted: acc };
  }, [listings]);

  return (
    <aside
      className={cn(
        "shrink-0 w-[320px] border-l bg-paper-2/40 flex flex-col h-full",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.08)" }}
      aria-label="Candidates"
    >
      <header
        className="shrink-0 px-4 py-3 border-b"
        style={{ borderColor: "rgba(15,15,15,0.08)" }}
      >
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="font-display font-bold text-ink text-body">
            Candidates
          </h2>
          <span className="text-micro text-ink-3 font-mono">
            {discovered.length} new · {accepted.length} accepted
          </span>
        </div>
        <p className="text-micro text-ink-3 mt-0.5">
          Listings Goti found. Start negotiation when one looks good.
        </p>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 flex flex-col gap-2">
        {!loaded ? (
          <div className="text-caption text-ink-3 px-2">Loading…</div>
        ) : discovered.length === 0 && accepted.length === 0 ? (
          <div className="text-caption text-ink-3 px-2">
            No candidates yet. Goti will surface listings here as it
            searches.
          </div>
        ) : (
          <>
            {discovered.length > 0 ? (
              <>
                <SectionLabel>Discovered</SectionLabel>
                {discovered.map((l) => (
                  <DiscoveredCard
                    key={l.id}
                    huntId={huntId}
                    listing={l}
                    onStarted={onStarted}
                  />
                ))}
              </>
            ) : null}
            {accepted.length > 0 ? (
              <>
                <SectionLabel>Accepted</SectionLabel>
                {accepted.map((l) => (
                  <AcceptedCard
                    key={l.id}
                    listing={l}
                    onOpen={() => l.job_id && onStarted(l.job_id)}
                  />
                ))}
              </>
            ) : null}
          </>
        )}
      </div>
    </aside>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold px-1 py-1 mt-1">
      {children}
    </div>
  );
}

interface DiscoveredCardProps {
  huntId: string;
  listing: HuntListingEntry;
  onStarted: (jobId: string) => void;
}

function DiscoveredCard({ huntId, listing, onStarted }: DiscoveredCardProps) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleStart() {
    if (starting) return;
    setStarting(true);
    setError(null);
    try {
      const res = await startNegotiation(huntId, listing.id);
      onStarted(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start");
    } finally {
      setStarting(false);
    }
  }

  return (
    <article
      className="rounded-xl border bg-paper p-3 flex flex-col gap-2"
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <header className="flex items-baseline justify-between gap-2">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
          {marketplaceLabel(listing.marketplace)}
        </span>
        <span className="font-display font-bold text-ink text-body">
          ${Math.round(listing.price ?? 0)}
        </span>
      </header>
      <h3 className="text-caption font-display font-semibold text-ink leading-snug">
        {listing.title || "Untitled listing"}
      </h3>
      {listing.description ? (
        <p className="text-micro text-ink-2 line-clamp-2 leading-snug">
          {listing.description}
        </p>
      ) : null}
      <button
        type="button"
        onClick={handleStart}
        disabled={starting}
        className={cn(
          "rounded-lg border bg-orange px-2.5 py-1 text-micro font-semibold text-paper",
          "shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95 transition",
          "disabled:opacity-50 disabled:cursor-not-allowed"
        )}
        style={{ borderColor: "rgba(15,15,15,0.5)" }}
      >
        {starting ? "Starting…" : "Start negotiation"}
      </button>
      {error ? (
        <p className="text-micro text-accent">{error}</p>
      ) : null}
    </article>
  );
}

interface AcceptedCardProps {
  listing: HuntListingEntry;
  onOpen: () => void;
}

function AcceptedCard({ listing, onOpen }: AcceptedCardProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "text-left rounded-xl border bg-paper p-3 flex flex-col gap-1.5",
        "hover:bg-paper-3 transition"
      )}
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
          {marketplaceLabel(listing.marketplace)}
        </span>
        <span className="text-micro text-ink-2">
          {statusBadge(listing.job_status)}
        </span>
      </div>
      <h3 className="text-caption font-display font-semibold text-ink leading-snug">
        {listing.title || "Negotiation"}
      </h3>
      <span className="text-micro text-ink-3 underline-offset-2 underline">
        Open chat →
      </span>
    </button>
  );
}

function statusBadge(s?: string | null): string {
  if (!s) return "—";
  if (s === "awaiting_user_approval") return "needs approval";
  if (s === "awaiting_seller_reply") return "waiting reply";
  if (s === "closed") return "closed";
  if (s === "cancelled") return "cancelled";
  return s;
}

function marketplaceLabel(m?: string | null): string {
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
      return m ?? "";
  }
}
