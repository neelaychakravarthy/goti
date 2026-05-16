"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { HuntKey } from "@/lib/hunts";
import { cn } from "@/lib/utils";

interface HubHeaderProps {
  className?: string;
  title?: string;
  sub?: string;
  /** Optional one-line status appended below `sub` (e.g. "8 found · review options"). */
  status?: string;
  /** When false, hide the inline tab pills (title + sub only). */
  showTabs?: boolean;
  /**
   * Active hunt — controls hunt-aware tab hrefs. When set to "lebron" or
   * "couch", tabs are hidden because downstream pages render preview states.
   */
  huntKey?: HuntKey;
}

interface TabSpec {
  label: string;
  href: string;
  match: RegExp;
}

function tabsFor(huntKey: HuntKey): TabSpec[] {
  if (huntKey === "standing-desk") {
    return [
      {
        label: "Best options",
        href: "/compare?hunt=standing-desk",
        match: /^\/compare/,
      },
      {
        label: "Next moves",
        href: "/approve?hunt=standing-desk",
        match: /^\/approve/,
      },
      { label: "Messages", href: "/deal/j-uplift", match: /^\/deal/ },
      {
        label: "Playbook",
        href: "/playbook?hunt=standing-desk",
        match: /^\/playbook/,
      },
    ];
  }
  // lebron / couch — preview build; no tabs are wired.
  return [];
}

/**
 * Hub context row rendered above page content on search/compare/approve.
 * Title + sub on the left, optional tab pills on the right.
 */
export function HubHeader({
  className,
  title = "Standing desk under $250",
  sub = "Goti is finding your best options across Facebook Marketplace, Nextdoor, Craigslist, and OfferUp.",
  status,
  showTabs = true,
  huntKey = "standing-desk",
}: HubHeaderProps) {
  const pathname = usePathname() ?? "";
  const tabs = tabsFor(huntKey);
  const tabsVisible = showTabs && tabs.length > 0;

  return (
    <div
      className={cn(
        "w-full border-b bg-paper",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.08)" }}
    >
      <div className="mx-auto max-w-[1200px] flex flex-wrap items-start justify-between gap-4 px-6 py-4">
        <div className="flex flex-col gap-1 min-w-0">
          <h2
            className="font-display font-bold text-ink leading-tight tracking-tight"
            style={{ fontSize: "22px" }}
          >
            {title}
          </h2>
          <p className="text-caption text-ink-2 max-w-[640px]">{sub}</p>
          {status ? (
            <p className="text-micro text-ink-3 mt-0.5 font-medium">
              {status}
            </p>
          ) : null}
        </div>

        {tabsVisible ? (
          <nav
            aria-label="Hub sections"
            className="flex flex-wrap items-center gap-1.5 shrink-0"
          >
            {tabs.map((t) => {
              const active = t.match.test(pathname);
              return (
                <Link
                  key={t.href}
                  href={t.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex items-center rounded-full px-2.5 py-1 text-micro transition-colors",
                    active
                      ? "bg-panel-dark text-paper"
                      : "bg-paper-2 text-ink-2 hover:text-ink hover:bg-paper-3"
                  )}
                >
                  {t.label}
                </Link>
              );
            })}
          </nav>
        ) : null}
      </div>
    </div>
  );
}
