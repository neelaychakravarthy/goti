import { StatusChip } from "@/components/ui/status-chip";
import { cn } from "@/lib/utils";
import type { ConversationMessage } from "@/types";

interface ConversationBubbleProps {
  message: ConversationMessage;
}

export function ConversationBubble({ message }: ConversationBubbleProps) {
  const isGoti = message.from === "goti_draft";
  const wasSent = message.status === "sent";

  return (
    <div className={cn("flex flex-col gap-1", isGoti ? "items-end" : "items-start")}>
      <div className="flex items-center gap-2 text-micro text-ink-3">
        <span className="font-medium text-ink-2">
          {isGoti ? "Goti (prepared)" : message.speaker ?? "Seller"}
        </span>
        <span aria-hidden>·</span>
        <span>{message.at}</span>
      </div>

      <div
        className={cn(
          "max-w-[88%] rounded-2xl px-4 py-2.5 text-body leading-relaxed",
          isGoti
            ? "bg-panel-dark text-paper border border-ink-line"
            : "bg-paper-2 text-ink border border-ink-line/15"
        )}
      >
        {message.text}
      </div>

      {isGoti ? (
        <StatusChip tone={wasSent ? "neutral" : "draft_saved"}>
          {wasSent ? `Sent · ${message.at}` : "Draft saved · not sent"}
        </StatusChip>
      ) : null}
    </div>
  );
}
