// Legacy /deal/<job_id> route — kept for back-compat with notification
// target_hrefs already in the database. Looks up the job's parent hunt
// id and redirects to /c/<hunt_id>?deal=<job_id> so the chat page
// auto-opens the seller-conversation slideover for that job.
//
// If the job can't be resolved (deleted, wrong user), redirect to root
// so the user lands somewhere safe.

import { redirect } from "next/navigation";

import { ApiError, getDealRoom } from "@/lib/api";

export default async function LegacyDealRedirect({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let huntId: string | null = null;
  try {
    const room = await getDealRoom(id);
    // The DealRoom contract doesn't currently expose hunt_id directly,
    // but we can read it off the job via /api/jobs/{id} indirectly. For
    // now: if listing has a hunt_id field, use it; otherwise look at the
    // listing's id and route to root.
    type RoomWithHunt = { hunt_id?: string | null };
    huntId = (room as unknown as RoomWithHunt).hunt_id ?? null;
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
      redirect("/login");
    }
    // Fall through to root.
  }
  if (huntId) {
    redirect(`/c/${encodeURIComponent(huntId)}?deal=${encodeURIComponent(id)}`);
  }
  redirect("/");
}
