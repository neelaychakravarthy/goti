"use client";

import { useMemo, useState } from "react";

import { QuickAnswerStrip } from "@/components/compare/quick-answer-strip";
import { SellerCardsGrid } from "@/components/compare/seller-cards-grid";
import { SelectionSummaryBar } from "@/components/compare/selection-summary-bar";
import { StackHero } from "@/components/compare/stack-hero";
import { TwoPanel } from "@/components/layout/two-panel";
import { NextMovesPanel } from "@/components/nextmoves/next-moves-panel";
import listings from "@/mocks/listings.json";
import nextMovesCompare from "@/mocks/next-moves/compare.json";
import type { Listing, NextMoveItem } from "@/types";

// Demo seeds: pre-select FlexiSpot + Uplift to match the story Goti is telling.
const INITIAL_SELECTED = new Set<string>(["l-flexispot", "l-uplift"]);

export function CompareDeskContent() {
  const all = listings as Listing[];
  const [selectedIds, setSelectedIds] =
    useState<ReadonlySet<string>>(INITIAL_SELECTED);

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const selectedTitles = useMemo(
    () => all.filter((l) => selectedIds.has(l.id)).map((l) => l.title),
    [all, selectedIds]
  );

  const heroRecommendation: NextMoveItem = {
    id: "nm-c-hero",
    kind: "recommendation",
    title: "Goti's plan",
    body:
      "Pursue FlexiSpot first for price proof, then use that lower offer to ask Uplift for $205.",
  };

  return (
    <>
      <div className="mx-auto w-full max-w-[1200px] flex flex-col gap-6 px-6 py-8">
        <div className="grid grid-cols-12 gap-4 items-stretch">
          <div className="col-span-12 lg:col-span-8">
            <StackHero
              brief="standing desk · under $250 · near San Francisco · avoid IKEA"
              stats={{
                found: 12,
                worth_pursuing: 4,
                best_likely_close: 195,
                projected_savings: "$35–$80",
              }}
            />
          </div>
          <div className="col-span-12 lg:col-span-4">
            <NextMovesPanel
              items={[heroRecommendation]}
              countOverride={1}
              className="h-full max-w-none ml-0"
            />
          </div>
        </div>

        <QuickAnswerStrip />

        <TwoPanel
          asideCols={4}
          aside={
            <NextMovesPanel items={nextMovesCompare as NextMoveItem[]} />
          }
        >
          <SellerCardsGrid
            listings={all}
            selectedIds={selectedIds}
            onToggle={toggle}
          />
        </TwoPanel>
      </div>

      <SelectionSummaryBar
        count={selectedIds.size}
        selectedTitles={selectedTitles}
        projectedSavings="$35–$80"
        href="/approve?hunt=standing-desk"
        huntKey="standing-desk"
      />
    </>
  );
}
