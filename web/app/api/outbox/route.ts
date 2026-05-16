import outbox from "@/mocks/outbox.json";
import type { Outbox } from "@/types";

export async function GET(): Promise<Response> {
  return Response.json(outbox as Outbox);
}
