import { Conversation } from "@/components/deal/conversation";
import { ListingDetailCard } from "@/components/deal/listing-detail-card";
import { NextMoveCard } from "@/components/deal/next-move-card";
import type { DealRoom } from "@/types";

interface DealRoomLayoutProps {
  room: DealRoom;
}

export function DealRoomLayout({ room }: DealRoomLayoutProps) {
  return (
    <div className="grid grid-cols-12 gap-5">
      <div className="col-span-12 lg:col-span-4">
        <ListingDetailCard
          listing={room.listing}
          sellerCheck={room.seller_check}
        />
      </div>
      <div className="col-span-12 lg:col-span-5">
        <Conversation
          listing={room.listing}
          messages={room.conversation}
          safetyAfter={room.safety_banner_after}
        />
      </div>
      <div className="col-span-12 lg:col-span-3">
        <NextMoveCard move={room.next_move} />
      </div>
    </div>
  );
}
