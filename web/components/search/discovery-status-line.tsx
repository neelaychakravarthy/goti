import { cn } from "@/lib/utils";

interface DiscoveryStatusLineProps {
  text: string;
  done?: boolean;
  className?: string;
}

/**
 * Single-line activity readout — pulsing dot + the agent's current step.
 * Switches to a green dot once discovery is complete.
 */
export function DiscoveryStatusLine({
  text,
  done = false,
  className,
}: DiscoveryStatusLineProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-lg bg-paper-2 border border-ink-line/15 px-3 py-2",
        className
      )}
    >
      <span
        aria-hidden
        className={cn(
          "inline-block size-2 rounded-full",
          done ? "bg-green" : "bg-orange goti-pulse-dot"
        )}
      />
      <span className="text-caption text-ink-2">
        <span className="text-ink font-medium">
          {done ? "Goti finished checking. " : "Goti is checking. "}
        </span>
        {text}
      </span>
    </div>
  );
}
