import Link from "next/link";

import { cn } from "@/lib/utils";

interface StepPillProps {
  num: number;
  label: string;
  href: string;
  active?: boolean;
  /** When true, render as a non-interactive span (preview build). */
  disabled?: boolean;
  className?: string;
}

/**
 * Numbered step pill. Active gets the dark fill; inactive uses paper-2 + ink.
 * When `disabled`, renders as a span instead of a link.
 */
export function StepPill({
  num,
  label,
  href,
  active = false,
  disabled = false,
  className,
}: StepPillProps) {
  const sharedClassName = cn(
    "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-caption transition-colors",
    active
      ? "bg-panel-dark text-paper"
      : "bg-paper-2 text-ink-2 hover:text-ink hover:bg-paper-3",
    disabled && "opacity-60 cursor-not-allowed hover:bg-paper-2 hover:text-ink-2",
    className
  );

  const inner = (
    <>
      <span
        className={cn(
          "inline-flex items-center justify-center size-5 rounded-full text-micro font-display font-bold",
          active ? "bg-paper text-ink" : "bg-paper text-ink-2"
        )}
      >
        {num}
      </span>
      <span className="font-medium">{label}</span>
    </>
  );

  if (disabled) {
    return (
      <span
        aria-disabled="true"
        title="Preview build"
        className={sharedClassName}
      >
        {inner}
      </span>
    );
  }

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={sharedClassName}
    >
      {inner}
    </Link>
  );
}
