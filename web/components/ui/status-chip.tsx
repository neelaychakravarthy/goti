import { cn } from "@/lib/utils";

type ChipTone =
  | "waiting"
  | "selected"
  | "needs_edit"
  | "lower_priority"
  | "connected"
  | "available"
  | "search_only"
  | "draft_saved"
  | "not_sent"
  | "neutral";

interface StatusChipProps {
  tone: ChipTone;
  children: React.ReactNode;
  className?: string;
}

const TONE: Record<ChipTone, string> = {
  waiting:
    "bg-orange-soft text-ink border-orange/40",
  selected:
    "bg-green-soft text-green border-green/30",
  needs_edit:
    "bg-paper-2 text-ink border-ink-line/30",
  lower_priority:
    "bg-paper-2 text-ink-3 border-ink-line/15",
  connected:
    "bg-green-soft text-green border-green/30",
  available:
    "bg-paper-2 text-ink-2 border-ink-line/20",
  search_only:
    "bg-paper-2 text-ink-3 border-ink-line/20",
  draft_saved:
    "bg-paper-2 text-ink-2 border-ink-line/30",
  not_sent:
    "bg-paper-2 text-ink-2 border-ink-line/30",
  neutral:
    "bg-paper-2 text-ink-2 border-ink-line/20",
};

export function StatusChip({ tone, children, className }: StatusChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
        "text-micro font-medium",
        TONE[tone],
        className
      )}
    >
      {children}
    </span>
  );
}
