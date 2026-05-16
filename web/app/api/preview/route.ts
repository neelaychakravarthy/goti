import preview from "@/mocks/stack-preview-mini.json";
import type { StackPreviewMini } from "@/types";

export async function GET(): Promise<Response> {
  return Response.json(preview as StackPreviewMini);
}
