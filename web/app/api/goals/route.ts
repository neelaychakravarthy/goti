import type { BuyingBrief } from "@/types";

export async function POST(request: Request): Promise<Response> {
  // Persist-as-no-op for the demo: the route accepts the buying brief shape and
  // returns an ok. The stack preview / deal stack is the same fixture either way.
  const body = (await request.json().catch(() => ({}))) as Partial<BuyingBrief>;
  return Response.json({ ok: true, item: body.item ?? "" });
}
