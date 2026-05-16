import { HubHeader } from "@/components/hub/hub-header";
import { TwoPanel } from "@/components/layout/two-panel";
import { NextMovesPanel } from "@/components/nextmoves/next-moves-panel";
import { DiscoveryFeed } from "@/components/search/discovery-feed";
import { ExtractedBriefChips } from "@/components/search/extracted-brief-chips";
import { HUNTS, resolveHunt, type HuntKey } from "@/lib/hunts";
import discoveryStages from "@/mocks/discovery-stages.json";
import listings from "@/mocks/listings.json";
import nextMovesSearch from "@/mocks/next-moves/search.json";
import type { DiscoveryStage, Listing, NextMoveItem } from "@/types";

interface HuntPageExtras {
  pillLabel: string;
  heroHeadline: string;
  heroForText: string;
}

const HUNT_EXTRAS: Record<HuntKey, HuntPageExtras> = {
  "standing-desk": {
    pillLabel: "1 · Searching",
    heroHeadline: "Goti is looking for your best options.",
    heroForText:
      'for: "standing desk under $250 near San Francisco · no IKEA · pickup today or tomorrow"',
  },
  lebron: {
    pillLabel: "1 · Searching",
    heroHeadline: "Goti found 4 LeBron pairs to consider.",
    heroForText:
      'for: "LeBron basketball shoes under $120 · size 11 · gently worn or new"',
  },
  couch: {
    pillLabel: "2 · Awaiting reply",
    heroHeadline: "Sellers are responding.",
    heroForText:
      'for: "couch near SF · under $600 · pickup with a van · pet-friendly fabric"',
  },
};

// Inline mock listings for the LeBron + Couch hunts. Re-uses MarketplacePhoto
// (its generic silhouette is acceptable across categories per the spec). Stays
// inside the four-marketplace contract typed in @/types.
const LEBRON_LISTINGS: Listing[] = [
  {
    id: "l-lebron-21",
    title: "Nike LeBron 21 'Conquer the Mind'",
    marketplace: "facebook",
    asking_price: 115,
    likely_close: 95,
    seller: {
      name: "Devon",
      avatar_initial: "D",
      rating: 4.9,
      sales: 34,
    },
    photos: {
      main: "main-l-lebron-21",
      thumbs: ["t1-l-lebron-21", "t2-l-lebron-21"],
    },
    location_label: "Bernal Heights",
    distance_mi: 2.1,
    posted_age_days: 2,
    pickup_constraint: "Meet near 24th BART",
    condition: "Worn 2x · box included",
    rank_label: "Best leverage",
    why_ranked: "Cleanest pair under budget with a recent posting.",
  },
  {
    id: "l-lebron-witness-8",
    title: "LeBron Witness 8 — size 11",
    marketplace: "offerup",
    asking_price: 95,
    likely_close: 80,
    seller: {
      name: "Priya",
      avatar_initial: "P",
      sales: 12,
      reply_speed: "usually replies in 2h",
    },
    photos: {
      main: "main-l-lebron-witness-8",
      thumbs: ["t1-l-lebron-witness-8", "t2-l-lebron-witness-8"],
    },
    location_label: "Outer Sunset",
    distance_mi: 4.6,
    posted_age_days: 1,
    pickup_constraint: "Porch pickup, weekdays after 6",
    condition: "Like new · tried once",
    rank_label: "Best quality",
    why_ranked: "Newest listing, fastest seller, fits the budget.",
  },
  {
    id: "l-lebron-soldier-13",
    title: "LeBron Soldier 13 (special edition)",
    marketplace: "nextdoor",
    asking_price: 105,
    likely_close: 88,
    seller: {
      name: "Marcus",
      avatar_initial: "M",
      verified: true,
    },
    photos: {
      main: "main-l-lebron-soldier-13",
      thumbs: ["t1-l-lebron-soldier-13", "t2-l-lebron-soldier-13"],
    },
    location_label: "Glen Park",
    distance_mi: 3.2,
    posted_age_days: 5,
    pickup_constraint: "Cash pickup",
    condition: "Good · light court wear",
    rank_label: "Fastest pickup",
    why_ranked: "Verified neighbor, listing has been up the longest.",
  },
  {
    id: "l-lebron-20",
    title: "Nike LeBron 20 low-top",
    marketplace: "craigslist",
    asking_price: 90,
    likely_close: 75,
    seller: {
      name: "private seller",
      avatar_initial: "P",
    },
    photos: {
      main: "main-l-lebron-20",
      thumbs: ["t1-l-lebron-20", "t2-l-lebron-20"],
    },
    location_label: "Excelsior",
    distance_mi: 5.4,
    posted_age_days: 9,
    pickup_constraint: "Public place pickup",
    condition: "Decent · creased toe box",
    rank_label: "Backup option",
    why_ranked: "Lowest price, but seller history is thin.",
  },
];

const LEBRON_STAGES: DiscoveryStage[] = [
  { t_ms: 0, status_text: "Searching Facebook Marketplace…" },
  {
    t_ms: 700,
    status_text: "Checking OfferUp",
    appears_listing_id: "l-lebron-21",
  },
  {
    t_ms: 1400,
    status_text: "Browsing Nextdoor",
    appears_listing_id: "l-lebron-witness-8",
  },
  {
    t_ms: 2100,
    status_text: "Scanning Craigslist",
    appears_listing_id: "l-lebron-soldier-13",
  },
  {
    t_ms: 2800,
    status_text: "Filtering size 11s only",
    appears_listing_id: "l-lebron-20",
  },
  { t_ms: 3500, status_text: "4 listings found · all worth reviewing" },
];

const LEBRON_NEXT_MOVES: NextMoveItem[] = [
  {
    id: "nm-lebron-1",
    kind: "discovery_update",
    title: "Goti found 4 LeBron pairs",
    body: "From Facebook Marketplace, OfferUp, Nextdoor, and Craigslist.",
    timestamp: "just now",
  },
  {
    id: "nm-lebron-2",
    kind: "recommendation",
    title: "Review LeBron options",
    body: "Devon's pair is the cleanest leverage; Priya's Witness 8 has the best condition-to-price ratio.",
    timestamp: "just now",
  },
];

const COUCH_LISTINGS: Listing[] = [
  {
    id: "l-couch-andes",
    title: "West Elm Andes Sofa (3-seater, charcoal)",
    marketplace: "facebook",
    asking_price: 580,
    likely_close: 480,
    seller: {
      name: "Jenna",
      avatar_initial: "J",
      verified: true,
      reply_speed: "usually replies in 1h",
    },
    photos: {
      main: "main-l-couch-andes",
      thumbs: ["t1-l-couch-andes", "t2-l-couch-andes"],
    },
    location_label: "Inner Richmond",
    distance_mi: 3.8,
    posted_age_days: 2,
    pickup_constraint: "Pickup with van, ground floor",
    condition: "Very good · light cat scratch on one arm",
    rank_label: "Best leverage",
    why_ranked: "Active seller already replied — strongest negotiation lane.",
  },
  {
    id: "l-couch-sven",
    title: "Article Sven Loveseat (oxford blue)",
    marketplace: "nextdoor",
    asking_price: 450,
    likely_close: 390,
    seller: {
      name: "Robert",
      avatar_initial: "R",
      verified: true,
    },
    photos: {
      main: "main-l-couch-sven",
      thumbs: ["t1-l-couch-sven", "t2-l-couch-sven"],
    },
    location_label: "Bernal Heights",
    distance_mi: 2.4,
    posted_age_days: 4,
    pickup_constraint: "Stairs · two-person carry",
    condition: "Excellent · moving sale",
    rank_label: "Best quality",
    why_ranked: "Lower price ceiling and verified neighbor.",
  },
];

const COUCH_STAGES: DiscoveryStage[] = [
  { t_ms: 0, status_text: "Pinging seller threads…" },
  {
    t_ms: 600,
    status_text: "Reading Jenna's latest reply",
    appears_listing_id: "l-couch-andes",
  },
  {
    t_ms: 1200,
    status_text: "Checking Article Sven thread",
    appears_listing_id: "l-couch-sven",
  },
  { t_ms: 1800, status_text: "2 sellers tracked · 1 reply waiting" },
];

const COUCH_NEXT_MOVES: NextMoveItem[] = [
  {
    id: "nm-couch-1",
    kind: "seller_reply",
    title: "Jenna replied: 'Still available, can drop $50'",
    body: "Goti can counter at $480 using the Sven loveseat ($450) as price proof. Approve to draft.",
    timestamp: "12 min ago",
  },
];

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ hunt?: string | string[] }>;
}) {
  const params = await searchParams;
  const raw = Array.isArray(params.hunt) ? params.hunt[0] : params.hunt;
  const huntKey = resolveHunt(raw);
  const cfg = HUNTS[huntKey];
  const extras = HUNT_EXTRAS[huntKey];

  const data = (() => {
    if (huntKey === "lebron") {
      return {
        listings: LEBRON_LISTINGS,
        stages: LEBRON_STAGES,
        nextMoves: LEBRON_NEXT_MOVES,
        showChips: false,
      };
    }
    if (huntKey === "couch") {
      return {
        listings: COUCH_LISTINGS,
        stages: COUCH_STAGES,
        nextMoves: COUCH_NEXT_MOVES,
        showChips: false,
      };
    }
    return {
      listings: listings as Listing[],
      stages: discoveryStages as DiscoveryStage[],
      nextMoves: nextMovesSearch as NextMoveItem[],
      showChips: true,
    };
  })();

  const reviewHref =
    huntKey === "standing-desk" ? "/compare?hunt=standing-desk" : undefined;

  return (
    <>
      <HubHeader
        title={cfg.title}
        sub={cfg.sub}
        status={cfg.status}
        huntKey={huntKey}
      />
      <div className="mx-auto max-w-[1200px] px-6 py-8">
        <TwoPanel
          asideCols={4}
          aside={<NextMovesPanel items={data.nextMoves} />}
        >
          <div className="flex flex-col gap-5">
            <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-panel-dark text-paper px-2.5 py-1 text-caption font-medium">
              {extras.pillLabel}
            </span>
            <h1 className="font-display font-bold text-ink text-display-2 leading-tight tracking-tight max-w-[640px]">
              {extras.heroHeadline}
            </h1>
            <p className="text-body text-ink-2 max-w-[640px]">
              {extras.heroForText}
            </p>

            {data.showChips ? <ExtractedBriefChips /> : null}

            <DiscoveryFeed
              listings={data.listings}
              stages={data.stages}
              reviewHref={reviewHref}
            />
          </div>
        </TwoPanel>
      </div>
    </>
  );
}
