import playbook from "@/mocks/playbook.json";
import type { Playbook } from "@/types";

export async function GET(): Promise<Response> {
  return Response.json(playbook as Playbook);
}
