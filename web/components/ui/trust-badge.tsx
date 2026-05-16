import { cn } from "@/lib/utils";

interface TrustBadgeProps {
  children: React.ReactNode;
  variant?: "verified" | "rating" | "neutral";
  className?: string;
}

/**
 * Small green pill for trust signals: "Verified neighbor", "4.8★", etc.
 */
export function TrustBadge({
  children,
  variant = "neutral",
  className,
}: TrustBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
        "text-micro font-medium text-green",
        "bg-green-soft border border-green/30",
        variant === "verified" && "before:content-['✓'] before:mr-0.5",
        className
      )}
      style={{ borderColor: "rgba(47,157,92,0.35)" }}
    >
      {children}
    </span>
  );
}
