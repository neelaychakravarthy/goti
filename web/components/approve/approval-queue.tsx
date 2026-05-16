import { ApprovalTicketCard } from "@/components/approve/approval-ticket";
import type { ApprovalTicket } from "@/types";

interface ApprovalQueueProps {
  tickets: ApprovalTicket[];
}

export function ApprovalQueue({ tickets }: ApprovalQueueProps) {
  return (
    <div className="flex flex-col gap-4">
      {tickets.map((t) => (
        <ApprovalTicketCard key={t.id} ticket={t} />
      ))}
    </div>
  );
}
