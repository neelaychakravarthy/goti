import type { MarketplaceChannel } from "@/types";

const PROVIDER_NAME: Record<string, string> = {
  facebook: "Facebook Marketplace",
  nextdoor: "Nextdoor",
  offerup: "OfferUp",
  craigslist: "Craigslist",
};

export async function POST(
  _request: Request,
  ctx: { params: Promise<{ provider: string }> }
): Promise<Response> {
  const { provider } = await ctx.params;
  const name = PROVIDER_NAME[provider];
  if (!name) {
    return new Response(JSON.stringify({ error: "unknown_provider" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  const channel: MarketplaceChannel = {
    marketplace: provider as MarketplaceChannel["marketplace"],
    name,
    status: provider === "craigslist" ? "search only" : "messages ready",
    state: "connected",
  };
  return Response.json(channel);
}
