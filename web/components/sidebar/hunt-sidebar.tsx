"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { GotiMark } from "@/components/topnav/goti-mark";
import { HuntRow, type HuntStatus } from "@/components/sidebar/hunt-row";
import { cn } from "@/lib/utils";

type HuntId = "standing-desk" | "lebron" | "couch";

interface Hunt {
  id: HuntId;
  title: string;
  subline: string;
  status: HuntStatus;
  href: string;
}

const HUNTS: Hunt[] = [
  {
    id: "standing-desk",
    title: "Standing desk under $250",
    subline: "4 found · 3 waiting",
    status: "waiting",
    href: "/search",
  },
  {
    id: "lebron",
    title: "LeBron basketball shoes",
    subline: "4 found · review options",
    status: "searching",
    href: "/search?hunt=lebron",
  },
  {
    id: "couch",
    title: "Couch near SF",
    subline: "seller replied",
    status: "reply",
    href: "/search?hunt=couch",
  },
];

const STANDING_DESK_PATH_MATCHERS = [
  /^\/search/,
  /^\/compare/,
  /^\/approve/,
  /^\/deal/,
  /^\/playbook/,
];

function isHuntActive(
  hunt: Hunt,
  pathname: string,
  huntParam: string | null
): boolean {
  if (hunt.id === "standing-desk") {
    if (!STANDING_DESK_PATH_MATCHERS.some((m) => m.test(pathname))) return false;
    return huntParam === null || huntParam === "standing-desk";
  }
  if (hunt.id === "lebron") {
    return pathname === "/search" && huntParam === "lebron";
  }
  if (hunt.id === "couch") {
    return pathname === "/search" && huntParam === "couch";
  }
  return false;
}

interface HuntSidebarProps {
  className?: string;
}

/**
 * Left rail listing the user's product hunts. Visible at lg+ widths.
 * Top: Goti mark + "New hunt" CTA. Body: hunt rows. Foot: Playbook link.
 */
export function HuntSidebar({ className }: HuntSidebarProps) {
  const pathname = usePathname() ?? "";
  const searchParams = useSearchParams();
  const huntParam = searchParams?.get("hunt") ?? null;
  const router = useRouter();

  return (
    <aside
      className={cn(
        "hidden lg:flex w-[260px] shrink-0 sticky top-0 self-start h-screen flex-col bg-paper-2 border-r",
        className
      )}
      style={{ borderColor: "rgba(15,15,15,0.08)" }}
      aria-label="Product hunts"
    >
      <div className="flex flex-col gap-3 px-4 pt-5 pb-4">
        <GotiMark />
        <button
          type="button"
          onClick={() => router.push("/start")}
          className={cn(
            "w-full inline-flex items-center justify-center gap-1.5 rounded-2xl border bg-paper px-3 py-2",
            "text-caption font-medium text-ink hover:bg-paper-3 transition-colors"
          )}
          style={{ borderColor: "rgba(15,15,15,0.12)" }}
        >
          <span aria-hidden className="text-ink-2">+</span>
          <span>New hunt</span>
        </button>
      </div>

      <div
        className="mx-4 border-t"
        style={{ borderColor: "rgba(15,15,15,0.08)" }}
      />

      <div className="px-4 pt-4 pb-2">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
          Product hunts
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto" aria-label="Hunts">
        <ul className="flex flex-col">
          {HUNTS.map((hunt, idx) => {
            const active = isHuntActive(hunt, pathname, huntParam);
            return (
              <li
                key={hunt.id}
                className={cn(idx > 0 && "border-t")}
                style={
                  idx > 0
                    ? { borderColor: "rgba(15,15,15,0.06)" }
                    : undefined
                }
              >
                <HuntRow
                  title={hunt.title}
                  subline={hunt.subline}
                  status={hunt.status}
                  active={active}
                  href={hunt.href}
                />
              </li>
            );
          })}
        </ul>
      </nav>

      <div
        className="border-t px-4 py-3"
        style={{ borderColor: "rgba(15,15,15,0.08)" }}
      >
        <Link
          href="/playbook"
          className="text-micro uppercase tracking-[0.08em] text-ink-2 hover:text-ink font-semibold"
        >
          Playbook
        </Link>
      </div>
    </aside>
  );
}
