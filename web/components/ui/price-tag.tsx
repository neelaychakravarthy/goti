import { cn } from "@/lib/utils";

interface PriceTagProps {
  amount: number;
  prefix?: string;
  suffix?: string;
  size?: "sm" | "md" | "lg";
  rotate?: number;
  className?: string;
}

/**
 * Yellow price tag chip with black border and small drop shadow. Used as the
 * price marker on listings and as the "Saved $X" stamp variant.
 */
export function PriceTag({
  amount,
  prefix = "$",
  suffix,
  size = "md",
  rotate = -1.5,
  className,
}: PriceTagProps) {
  const padding =
    size === "sm" ? "px-2 py-1 text-caption" : size === "lg" ? "px-4 py-2 text-headline" : "px-3 py-1.5 text-body";
  return (
    <span
      className={cn(
        "inline-flex items-baseline gap-0.5 rounded-md border bg-yellow font-display font-bold text-ink",
        "shadow-[0_2px_0_0_rgba(0,0,0,1)]",
        padding,
        className
      )}
      style={{
        borderColor: "var(--yellow-deep)",
        transform: `rotate(${rotate}deg)`,
      }}
    >
      <span className="text-ink-2 font-normal text-[0.75em]">{prefix}</span>
      <span>{amount.toLocaleString("en-US")}</span>
      {suffix ? <span className="text-ink-2 font-normal text-[0.75em] ml-0.5">{suffix}</span> : null}
    </span>
  );
}
