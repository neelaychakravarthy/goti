export type HuntKey = "standing-desk" | "lebron" | "couch";

export const HUNTS: Record<HuntKey, { title: string; sub: string; status: string }> = {
  "standing-desk": {
    title: "Standing desk under $250",
    sub: "Goti is finding your best options across Facebook Marketplace, Nextdoor, Craigslist, and OfferUp.",
    status: "4 found · 3 waiting on approval",
  },
  lebron: {
    title: "LeBron basketball shoes",
    sub: "Goti is finding sneakers under $120 near you across Facebook Marketplace, OfferUp, eBay, and Mercari.",
    status: "4 found · review options",
  },
  couch: {
    title: "Couch near SF",
    sub: "Goti is tracking sellers in your area.",
    status: "1 seller replied · awaiting your move",
  },
};

export function resolveHunt(raw: unknown): HuntKey {
  if (raw === "lebron" || raw === "couch" || raw === "standing-desk") return raw;
  return "standing-desk";
}
