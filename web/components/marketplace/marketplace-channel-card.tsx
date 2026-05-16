import { StatusChip } from "@/components/ui/status-chip";
import { cn, marketplaceColor } from "@/lib/utils";
import type { MarketplaceChannel } from "@/types";

interface MarketplaceChannelCardProps {
  channel: MarketplaceChannel;
  className?: string;
}

/**
 * Single marketplace row: dot + full name + role chip + state chip.
 * e.g. "Facebook Marketplace — messages ready — connected".
 */
export function MarketplaceChannelCard({
  channel,
  className,
}: MarketplaceChannelCardProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-lg border bg-paper px-3 py-2.5",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span
          aria-hidden
          className="size-2 rounded-full"
          style={{ background: marketplaceColor(channel.marketplace) }}
        />
        <span className="font-medium text-body text-ink truncate">
          {channel.name}
        </span>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <StatusChip tone={channel.status === "messages ready" ? "neutral" : "search_only"}>
          {channel.status}
        </StatusChip>
        <StatusChip tone={channel.state === "connected" ? "connected" : "available"}>
          {channel.state}
        </StatusChip>
      </div>
    </div>
  );
}
