import { NextMoveCard } from "@/components/nextmoves/next-move-card";
import { cn } from "@/lib/utils";
import type { NextMoveItem } from "@/types";

interface NextMovesPanelProps {
  items: NextMoveItem[];
  className?: string;
  /** Optional override for the displayed count. Defaults to items.length. */
  countOverride?: number;
  emptyHint?: string;
}

/**
 * Right-rail panel listing pending Next Moves the buyer agent has surfaced.
 * Subtle border, paper-2 base, ~380px max width.
 */
export function NextMovesPanel({
  items,
  className,
  countOverride,
  emptyHint,
}: NextMovesPanelProps) {
  const count = countOverride ?? items.length;

  return (
    <section
      className={cn(
        "rounded-2xl border bg-paper-2 p-4 flex flex-col gap-3 max-w-[380px] w-full ml-auto",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.14)" }}
    >
      <header className="flex items-center justify-between">
        <span className="text-micro uppercase tracking-wider text-ink-3 font-semibold">
          Next Moves
        </span>
        <span className="text-micro text-ink-2 font-medium">({count})</span>
      </header>

      {items.length === 0 ? (
        <p className="text-caption text-ink-3 italic">
          {emptyHint ?? "Goti will surface its next moves here."}
        </p>
      ) : (
        <div className="flex flex-col gap-2.5">
          {items.map((it) => (
            <NextMoveCard key={it.id} item={it} />
          ))}
        </div>
      )}
    </section>
  );
}
