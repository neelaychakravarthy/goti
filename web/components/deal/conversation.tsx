import { ConversationBubble } from "@/components/deal/conversation-bubble";
import { ConversationSafetyBanner } from "@/components/deal/conversation-safety-banner";
import { MarketplaceBadge } from "@/components/marketplace/marketplace-badge";
import { marketplaceLabel } from "@/lib/utils";
import type { ConversationMessage, Listing } from "@/types";

interface ConversationProps {
  listing: Listing;
  messages: ConversationMessage[];
  safetyAfter: string;
}

export function Conversation({
  listing,
  messages,
  safetyAfter,
}: ConversationProps) {
  return (
    <section className="flex flex-col gap-3">
      <header
        className="rounded-2xl border bg-paper px-4 py-3 flex items-center justify-between gap-3"
        style={{ borderColor: "rgba(15,15,15,0.18)" }}
      >
        <div className="flex flex-col gap-1 min-w-0">
          <div className="text-micro uppercase tracking-wider text-ink-3 font-semibold">
            {`${marketplaceLabel(listing.marketplace)} conversation`}
          </div>
          <div className="flex items-center gap-2 min-w-0">
            <MarketplaceBadge marketplace={listing.marketplace} size="sm" />
            <span className="text-caption text-ink-2 truncate">
              {listing.seller.name} · {listing.title}
            </span>
          </div>
        </div>
        <span
          className="inline-flex items-center gap-1.5 rounded-full border bg-green-soft px-2.5 py-1 text-caption font-medium text-green shrink-0"
          style={{ borderColor: "rgba(47,157,92,0.35)" }}
        >
          <span aria-hidden className="size-1.5 rounded-full bg-green" />
          Goti paused
        </span>
      </header>

      <div className="flex flex-col gap-4">
        {messages.map((m, i) => (
          <ConversationBubble key={`${m.at}-${i}`} message={m} />
        ))}
      </div>

      <ConversationSafetyBanner after={safetyAfter} />
    </section>
  );
}
