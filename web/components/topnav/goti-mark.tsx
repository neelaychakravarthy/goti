import Link from "next/link";

import { cn } from "@/lib/utils";

interface GotiMarkProps {
  className?: string;
  href?: string;
  showSubtitle?: boolean;
}

/**
 * Goti wordmark: yellow tile with "G", then "Goti / Deal stack builder".
 */
export function GotiMark({
  className,
  href = "/",
  showSubtitle = true,
}: GotiMarkProps) {
  return (
    <Link
      href={href}
      className={cn("inline-flex items-center gap-2.5 group", className)}
    >
      <span
        className="inline-flex items-center justify-center size-9 rounded-md border bg-yellow text-ink font-display font-bold text-headline shadow-[0_2px_0_0_rgba(0,0,0,1)]"
        style={{ borderColor: "var(--yellow-deep)" }}
      >
        G
      </span>
      <span className="flex flex-col leading-tight">
        <span className="font-display font-bold text-ink text-body">Goti</span>
        {showSubtitle ? (
          <span className="text-micro text-ink-3">Buyer agent</span>
        ) : null}
      </span>
    </Link>
  );
}
