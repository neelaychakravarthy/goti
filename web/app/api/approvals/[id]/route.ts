export async function POST(
  request: Request,
  ctx: { params: Promise<{ id: string }> }
): Promise<Response> {
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => ({}))) as {
    decision?: string;
    edited_text?: string;
  };
  return Response.json({
    ok: true,
    approval_id: id,
    decision: body.decision ?? "approve",
    edited: Boolean(body.edited_text),
  });
}
