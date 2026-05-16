"use client";

import { ProductResultCard } from "@/components/compare/product-result-card";
import type { Listing } from "@/types";

interface SellerCardsGridProps {
  listings: Listing[];
  selectedIds: ReadonlySet<string>;
  onToggle: (id: string) => void;
}

export function SellerCardsGrid({
  listings,
  selectedIds,
  onToggle,
}: SellerCardsGridProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {listings.map((l, i) => (
        <ProductResultCard
          key={l.id}
          listing={l}
          rank={i + 1}
          selected={selectedIds.has(l.id)}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}
