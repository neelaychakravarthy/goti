"use client";

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";

import { CheckReplyButton } from "@/components/deal/check-reply-button";
import { Conversation } from "@/components/deal/conversation";
import { ListingDetailCard } from "@/components/deal/listing-detail-card";
import { NextMoveCard } from "@/components/deal/next-move-card";
import type { DealRoom } from "@/types";

interface DealRoomLayoutProps {
  room: DealRoom;
  /** Number of OTHER active sibling jobs in the same hunt — surfaced
   * in the finalize-close confirmation modal so the user knows how
   * many decline messages will fan out on confirm. Defaults to 0 when
   * the server can't compute it (e.g. a job with no parent hunt). */
  siblingCount?: number;
}

export function DealRoomLayout({ room, siblingCount = 0 }: DealRoomLayoutProps) {
  const router = useRouter();

  // Poll the server every 2s while the negotiator is still drafting
  // async. The negotiator runs in a background asyncio task on the
  // server (spawned by POST /api/jobs/{id}/draft-next as of Phase D);
  // it calls app.pause() which writes an ApprovalQueueItem with the
  // draft. ``router.refresh()`` triggers a server-side re-fetch so the
  // deal page picks up the new draft on the next tick — no
  // client-side state plumbing required.
  const draftMissing = !room.next_move?.draft;
  const status = room.job_status;
  const hasBuyerMessages = useMemo(
    () => room.conversation.some((m) => m.from === "goti_draft"),
    [room.conversation],
  );
  // Phase D — only poll AFTER the user has clicked "Start negotiating"
  // (i.e. there's at least one buyer message in the thread OR a draft
  // has surfaced). Before the kickoff, the deal page is stable on the
  // "Start negotiating" CTA and there's no async work to wait for.
  const shouldPoll =
    draftMissing &&
    hasBuyerMessages &&
    (status === "active" || status === "awaiting_user_approval" || !status);

  useEffect(() => {
    if (!shouldPoll) return;
    const interval = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(interval);
  }, [shouldPoll, router]);

  // Phase D — "Check for reply" should be available whenever the job
  // is still negotiating (active or awaiting_seller_reply), not just
  // the awaiting_seller_reply branch. Surfacing it on active too lets
  // the user re-check after they sent the opening message but the
  // server hasn't bumped status yet, or to defensively re-check
  // independent of timing.
  const showCheckReply =
    room.job_status === "awaiting_seller_reply" ||
    room.job_status === "active";

  return (
    <div className="flex flex-col gap-5">
      {showCheckReply && hasBuyerMessages ? (
        <section className="rounded-2xl border border-ink-line/20 bg-paper-2/60 px-5 py-4 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-col gap-1 max-w-[640px]">
            <h2 className="font-display font-semibold text-ink text-headline leading-tight">
              {room.job_status === "awaiting_seller_reply"
                ? "Awaiting the seller's reply."
                : "Negotiating."}
            </h2>
            <p className="text-caption text-ink-2">
              Goti doesn&apos;t poll in the background — tap below when
              you&apos;re ready to check for a new message. Goti will draft
              a counter for your approval if the seller has responded.
            </p>
          </div>
          <CheckReplyButton jobId={room.job_id} className="shrink-0" />
        </section>
      ) : null}

      {/* Slideover-friendly stacked layout. The three panels stack
          vertically inside the slideover panel (~820px wide) so nothing
          gets squished into 240px columns. NextMoveCard is the primary
          action surface and sits at the top; the listing detail + the
          conversation flow below it where there's room to breathe. */}
      <div className="flex flex-col gap-4">
        <NextMoveCard
          move={room.next_move}
          approvalRequestId={room.next_move.approval_request_id ?? null}
          jobStatus={room.job_status ?? null}
          hasBuyerMessages={hasBuyerMessages}
          siblingCount={siblingCount}
        />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ListingDetailCard
            listing={room.listing}
            sellerCheck={room.seller_check}
          />
          <Conversation
            listing={room.listing}
            messages={room.conversation}
            safetyAfter={room.safety_banner_after}
          />
        </div>
      </div>
    </div>
  );
}
