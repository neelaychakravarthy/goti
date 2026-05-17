import { cn } from "@/lib/utils";

interface SavingsStampProps {
  amount: number;
  rotate?: number;
  className?: string;
}

/**
 * Yellow stamp: "Saved $35". Read like a small physical receipt.
 */
export function SavingsStamp({
  amount,
  rotate = -3,
  className,
}: SavingsStampProps) {
  return (
    <span
      className={cn(
        "inline-flex flex-col items-center justify-center rounded-md border bg-yellow text-ink",
        "px-3 py-1.5 shadow-[0_2px_0_0_rgba(0,0,0,1)]",
        className
      )}
      style={{
        borderColor: "var(--yellow-deep)",
        transform: `rotate(${rotate}deg)`,
      }}
    >
      <span className="text-[10px] font-medium uppercase tracking-wider text-ink-2">
        Saved
      </span>
      <span className="font-display font-bold text-body leading-none mt-0.5">
        ${amount}
      </span>
    </span>
  );
}
