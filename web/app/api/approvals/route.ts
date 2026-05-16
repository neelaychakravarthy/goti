import approvals from "@/mocks/approvals.json";
import type { ApprovalTicket } from "@/types";

export async function GET(): Promise<Response> {
  return Response.json(approvals as ApprovalTicket[]);
}
