import { MarketplacePhoto } from "@/components/marketplace/marketplace-photo";
import { MarketplaceBadge } from "@/components/marketplace/marketplace-badge";
import { PriceTag } from "@/components/ui/price-tag";
import type { Listing, SellerCheck } from "@/types";

interface ListingDetailCardProps {
  listing: Listing;
  sellerCheck: SellerCheck;
}

export function ListingDetailCard({
  listing,
  sellerCheck,
}: ListingDetailCardProps) {
  return (
    <section className="flex flex-col gap-4">
      <div
        className="rounded-2xl border bg-paper-2 p-4 flex flex-col gap-3"
        style={{ borderColor: "rgba(15,15,15,0.18)" }}
      >
        <MarketplacePhoto
          listingId={listing.id}
          marketplace={listing.marketplace}
          size="md"
          cornerSticker="listing photo"
        />
        <div className="flex flex-col gap-2">
          <h3 className="text-headline font-display font-semibold text-ink leading-tight">
            {listing.title}
          </h3>
          <div className="flex items-center justify-between gap-2">
            <MarketplaceBadge marketplace={listing.marketplace} size="sm" />
            <PriceTag amount={listing.asking_price} size="sm" rotate={-2} />
          </div>
          <div className="text-caption text-ink-2">
            {listing.location_label}
            {listing.distance_mi ? ` · ${listing.distance_mi} mi` : ""}
          </div>
        </div>
      </div>

      <div
        className="rounded-2xl border bg-paper p-4 flex flex-col gap-3"
        style={{ borderColor: "rgba(15,15,15,0.18)" }}
      >
        <div className="text-micro uppercase tracking-wider text-ink-3 font-semibold">
          Seller check
        </div>
        <SellerRow label="Marketplace history" value={sellerCheck.history} />
        <SellerRow label="Location" value={sellerCheck.location} />
        <SellerRow label="Risk note" value={sellerCheck.risk} />
      </div>
    </section>
  );
}

function SellerRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 text-caption">
      <div className="flex flex-col">
        <span className="text-micro text-ink-3 font-medium">{label}</span>
        <span className="text-ink">{value}</span>
      </div>
      <span aria-hidden className="text-green pt-1">
        <svg viewBox="0 0 12 12" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M2 6.5L5 9.5L10 3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    </div>
  );
}
