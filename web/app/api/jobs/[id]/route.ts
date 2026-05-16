import jUplift from "@/mocks/deal-rooms/j-uplift.json";
import jFlexispot from "@/mocks/deal-rooms/j-flexispot.json";
import type { DealRoom } from "@/types";

const DEAL_ROOMS: Record<string, DealRoom> = {
  "j-uplift": jUplift as DealRoom,
  "j-flexispot": jFlexispot as DealRoom,
};

export async function GET(
  _request: Request,
  ctx: { params: Promise<{ id: string }> }
): Promise<Response> {
  const { id } = await ctx.params;
  const room = DEAL_ROOMS[id];
  if (!room) {
    return new Response(JSON.stringify({ error: "deal_room_not_found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }
  return Response.json(room);
}
