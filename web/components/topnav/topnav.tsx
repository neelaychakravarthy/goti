"use client";

import { usePathname, useSearchParams } from "next/navigation";

import { ActivityBell } from "@/components/topnav/activity-bell";
import { GotiMark } from "@/components/topnav/goti-mark";
import { StepPill } from "@/components/topnav/step-pill";
import { resolveHunt } from "@/lib/hunts";
import { cn } from "@/lib/utils";

const STEPS: { num: 1 | 2 | 3 | 4 | 5; label: string; href: string; match: RegExp }[] = [
  { num: 1, label: "Search", href: "/search", match: /^\/search/ },
  { num: 2, label: "Compare", href: "/compare", match: /^\/compare/ },
  { num: 3, label: "Approve", href: "/approve", match: /^\/approve/ },
  { num: 4, label: "Close", href: "/deal/j-uplift", match: /^\/deal/ },
  { num: 5, label: "Learn", href: "/playbook", match: /^\/playbook/ },
];

interface TopNavProps {
  className?: string;
  /** Override the detected active step (used outside the (app) layout). */
  forceActive?: 1 | 2 | 3 | 4 | 5 | null;
}

export function TopNav({ className, forceActive }: TopNavProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const huntKey = resolveHunt(searchParams?.get("hunt") ?? undefined);
  const detected = STEPS.find((s) => s.match.test(pathname ?? ""))?.num ?? null;
  const active = forceActive ?? detected;

  // Non-desk hunts have no wired downstream pages — disable everything past Search.
  const previewHunt = huntKey !== "standing-desk";

  // Append ?hunt=... to step targets so navigation preserves hunt context.
  const huntQS =
    huntKey === "standing-desk" ? "" : `?hunt=${huntKey}`;

  return (
    <div
      className={cn(
        "sticky top-0 z-30 w-full border-b bg-paper/95 backdrop-blur",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.08)" }}
    >
      <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-4 px-6 py-2">
        <GotiMark showSubtitle={false} className="lg:hidden" />

        <nav
          aria-label="Workflow steps"
          className="hidden md:flex items-center gap-1 mx-auto"
        >
          {STEPS.map((s) => {
            // Step 1 (Search) and Step 5 (Learn) always work. Steps 2/3/4 are
            // gated by hunt — non-desk hunts have no wired Compare/Approve/Close.
            const stepDisabled = previewHunt && (s.num === 2 || s.num === 3 || s.num === 4);
            const stepHref = huntQS && (s.num === 1 || s.num === 5) ? `${s.href}${huntQS}` : s.href;

            return (
              <StepPill
                key={s.num}
                num={s.num}
                label={s.label}
                href={stepHref}
                active={active === s.num}
                disabled={stepDisabled}
                className={cn(
                  "px-2 py-0.5 text-micro",
                  active === s.num
                    ? ""
                    : "bg-paper-2 text-ink-3 hover:text-ink-2"
                )}
              />
            );
          })}
        </nav>

        <ActivityBell />
      </div>
    </div>
  );
}
