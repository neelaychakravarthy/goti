import { cn, marketplaceColor, marketplaceLabel } from "@/lib/utils";
import type { Marketplace } from "@/types";

interface MarketplaceBadgeProps {
  marketplace: Marketplace;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Small marketplace pill: colored dot + full marketplace name. Never initials —
 * "Facebook Marketplace", "Nextdoor", "OfferUp", "Craigslist".
 */
export function MarketplaceBadge({
  marketplace,
  size = "md",
  className,
}: MarketplaceBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border",
        "bg-paper text-ink",
        size === "sm" ? "px-2 py-0.5 text-micro" : "px-2.5 py-1 text-caption",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <span
        aria-hidden
        className="size-1.5 rounded-full"
        style={{ background: marketplaceColor(marketplace) }}
      />
      <span className="font-medium">{marketplaceLabel(marketplace)}</span>
    </span>
  );
}
