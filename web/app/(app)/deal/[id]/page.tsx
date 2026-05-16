import Link from "next/link";
import { notFound } from "next/navigation";

import { DealRoomLayout } from "@/components/deal/deal-room-layout";
import jUplift from "@/mocks/deal-rooms/j-uplift.json";
import jFlexispot from "@/mocks/deal-rooms/j-flexispot.json";
import type { DealRoom } from "@/types";

const ROOMS: Record<string, DealRoom> = {
  "j-uplift": jUplift as DealRoom,
  "j-flexispot": jFlexispot as DealRoom,
};

const TITLE_BY_ID: Record<string, string> = {
  "j-uplift": "Next move: ask Uplift for $205.",
  "j-flexispot": "Next move: confirm pickup with FlexiSpot.",
};

export default async function DealRoomPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const room = ROOMS[id];
  if (!room) {
    notFound();
  }

  return (
    <div className="mx-auto max-w-[1280px] flex flex-col gap-6 px-6 py-10">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex flex-col gap-2 max-w-[820px]">
          <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-panel-dark text-paper px-2.5 py-1 text-caption font-medium">
            4 · Close the deal
          </span>
          <h1 className="font-display font-bold text-ink text-display-2 md:text-display-1 leading-tight tracking-tight">
            {TITLE_BY_ID[id] ?? "Next move."}
          </h1>
          <p className="text-body text-ink-2">
            Goti is waiting for your approval before sending the next message.
          </p>
        </div>
        <Link
          href="/compare"
          className="text-caption text-ink-2 hover:text-ink underline-offset-2 hover:underline shrink-0 mt-2"
        >
          ← Back to best options
        </Link>
      </header>

      <DealRoomLayout room={room} />
    </div>
  );
}
