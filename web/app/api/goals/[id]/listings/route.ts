import listings from "@/mocks/listings.json";
import type { Listing } from "@/types";

export async function GET(): Promise<Response> {
  return Response.json(listings as Listing[]);
}
