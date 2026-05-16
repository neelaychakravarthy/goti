import jUplift from "@/mocks/deal-rooms/j-uplift.json";
import jFlexispot from "@/mocks/deal-rooms/j-flexispot.json";
import type { DealRoom, Job } from "@/types";

const ROOMS: DealRoom[] = [jUplift as DealRoom, jFlexispot as DealRoom];

export async function GET(): Promise<Response> {
  const jobs: Job[] = ROOMS.map((room) => ({
    job_id: room.job_id,
    listing_id: room.listing.id,
    title: room.listing.title,
    marketplace: room.listing.marketplace,
    status: "awaiting_approval",
    last_event_at: room.safety_banner_after,
  }));
  return Response.json(jobs);
}
