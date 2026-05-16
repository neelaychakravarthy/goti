import { cn } from "@/lib/utils";

interface RankingPillProps {
  rank: number;
  label: string;
  className?: string;
}

/**
 * Black pill with rank number and label, e.g. "#1 Best leverage".
 */
export function RankingPill({ rank, label, className }: RankingPillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full bg-panel-dark text-paper",
        "px-2.5 py-1 text-micro font-medium",
        className
      )}
    >
      <span className="font-display font-bold">#{rank}</span>
      <span>{label}</span>
    </span>
  );
}
