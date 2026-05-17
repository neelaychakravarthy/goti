"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

export type HuntStatus =
  | "waiting"
  | "searching"
  | "reply"
  | "paused"
  | "closed"
  | "error";

interface HuntRowProps {
  title: string;
  subline: string;
  status: HuntStatus;
  active?: boolean;
  href: string;
  className?: string;
}

/**
 * One product-hunt entry in the left sidebar. Renders a Next.js Link with a
 * status dot. Active hunt gets a thicker accent left border + raised bg.
 */
export function HuntRow({
  title,
  subline,
  status,
  active = false,
  href,
  className,
}: HuntRowProps) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group w-full text-left flex items-center gap-3 px-3 py-3 border-l-2 transition-colors",
        active
          ? "bg-paper text-ink"
          : "bg-transparent text-ink-2 hover:bg-paper-3/60 border-l-transparent",
        className
      )}
      style={
        active
          ? { borderLeftColor: "var(--accent)" }
          : undefined
      }
    >
      <span className="flex-1 min-w-0 flex flex-col leading-tight">
        <span
          className={cn(
            "text-caption truncate",
            active ? "font-semibold text-ink" : "font-medium text-ink"
          )}
        >
          {title}
        </span>
        <span className="text-micro text-ink-3 truncate normal-case tracking-normal">
          {subline}
        </span>
      </span>
      <StatusDot status={status} />
    </Link>
  );
}

function StatusDot({ status }: { status: HuntStatus }) {
  if (status === "waiting") {
    return (
      <span
        aria-hidden
        className="shrink-0 inline-block size-2.5 rounded-full"
        style={{ background: "var(--accent)" }}
      />
    );
  }
  if (status === "reply") {
    return (
      <span
        aria-hidden
        className="shrink-0 inline-block size-2.5 rounded-full"
        style={{ background: "var(--green)" }}
      />
    );
  }
  if (status === "paused") {
    return (
      <span
        aria-hidden
        className="shrink-0 inline-block size-2.5 rounded-full"
        style={{ background: "var(--yellow, #d97706)" }}
        title="Hunt paused"
      />
    );
  }
  if (status === "error") {
    return (
      <span
        aria-hidden
        className="shrink-0 inline-block size-2.5 rounded-full"
        style={{ background: "var(--orange)" }}
        title="Hunt errored"
      />
    );
  }
  if (status === "closed") {
    return (
      <span
        aria-hidden
        className="shrink-0 inline-block size-2.5 rounded-full"
        style={{
          background: "transparent",
          border: "1px solid var(--ink-3)",
        }}
        title="Hunt closed"
      />
    );
  }
  // searching
  return (
    <span
      aria-hidden
      className="shrink-0 inline-block size-2.5 rounded-full goti-pulse-dot"
      style={{ background: "var(--ink-3)" }}
    />
  );
}
