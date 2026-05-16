import channels from "@/mocks/channels.json";
import type { MarketplaceChannel } from "@/types";

export async function GET(): Promise<Response> {
  return Response.json(channels as MarketplaceChannel[]);
}
