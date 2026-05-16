import brief from "@/mocks/buying-brief.json";
import type { BuyingBrief } from "@/types";

export async function GET(): Promise<Response> {
  return Response.json(brief as BuyingBrief);
}
