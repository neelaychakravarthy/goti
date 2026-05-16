"use client";

import Link from "next/link";
import { useMemo, useState, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

const STORAGE_KEY = "goti_buying_request";

function subscribeNoop() {
  // localStorage doesn't fire a storage event for same-tab writes, and we
  // only need the snapshot at mount. Returning a no-op unsubscribe satisfies
  // useSyncExternalStore.
  return () => undefined;
}

function getSnapshot(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function getServerSnapshot(): string | null {
  return null;
}

const FALLBACK_CHIPS = [
  "Standing desk",
  "Under $250",
  "Near San Francisco",
  "Avoid IKEA",
  "Pickup today/tomorrow",
];

/**
 * Cheap heuristic parser for the round-1 NL string. Extracts a handful of
 * editable chips. Server-side parsing arrives with the Stream B agent
 * topology — until then this keeps the chips honest with whatever the user
 * actually typed.
 */
function parseChipsFromText(text: string): string[] {
  const t = text.trim();
  if (!t) return FALLBACK_CHIPS;

  const chips: string[] = [];

  // First noun-ish phrase before "under", "near", "no", "pickup", etc.
  const head = t.split(
    /\b(under|less than|below|near|in|no|without|avoid|pickup|by|today|tomorrow)\b/i
  )[0];
  const cleanedHead = head.replace(/^(find me a|find me an|find a|find an|i want a|i want an|i want|i need a|i need|looking for a|looking for an|looking for)\s+/i, "").trim();
  if (cleanedHead) {
    chips.push(capitalize(cleanedHead.replace(/[.,!?]+$/, "")));
  }

  // Price ceiling
  const priceMatch = t.match(/(?:under|below|less than|<|max|≤)\s*\$?\s*(\d[\d,]*)/i);
  if (priceMatch) {
    chips.push(`Under $${priceMatch[1].replace(/,/g, "")}`);
  }

  // Location
  const locationMatch =
    t.match(/\bnear\s+([A-Z][\w\s.'-]+?)(?=[.,;!?]|\sno\b|\sno\.|\swithout\b|\savoid\b|\spickup\b|$)/i) ??
    t.match(/\bin\s+([A-Z][\w\s.'-]+?)(?=[.,;!?]|\sno\b|\sno\.|\swithout\b|\savoid\b|\spickup\b|$)/i);
  if (locationMatch) {
    chips.push(`Near ${locationMatch[1].trim().replace(/[.,]$/, "")}`);
  }

  // Avoid phrases — split on "no X", "avoid X", "without X"
  const avoidRe = /\b(?:no|avoid|without)\s+([A-Za-z][\w\s-]*?)(?=[.,;!?]|\spickup\b|\sby\b|$)/gi;
  let am: RegExpExecArray | null;
  while ((am = avoidRe.exec(t)) !== null) {
    const phrase = am[1].trim().replace(/[.,]$/, "");
    if (phrase) chips.push(`Avoid ${capitalize(phrase)}`);
  }

  // Pickup window
  const pickupMatch = t.match(/pickup[^.,;!?]*?(today|tomorrow|this week|weekend)[^.,;!?]*/i);
  if (pickupMatch) {
    const span = pickupMatch[0]
      .replace(/^pickup\s*/i, "")
      .replace(/[.,;!?]$/, "")
      .trim();
    if (span) chips.push(`Pickup ${span.toLowerCase()}`);
  } else if (/\btomorrow\b/i.test(t) || /\btoday\b/i.test(t)) {
    const tw = /\btoday\b/i.test(t) && /\btomorrow\b/i.test(t)
      ? "today/tomorrow"
      : /\btoday\b/i.test(t) ? "today" : "tomorrow";
    chips.push(`Pickup ${tw}`);
  }

  return chips.length >= 2 ? chips : FALLBACK_CHIPS;
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function ExtractedBriefChips() {
  const raw = useSyncExternalStore(subscribeNoop, getSnapshot, getServerSnapshot);
  const [removed, setRemoved] = useState<Set<string>>(new Set());

  const chips = useMemo(() => {
    return parseChipsFromText(raw ?? "");
  }, [raw]);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips
        .filter((c) => !removed.has(c))
        .map((chip) => (
          <span
            key={chip}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full bg-paper-2 px-2.5 py-1",
              "text-caption text-ink border"
            )}
            style={{ borderColor: "rgba(15,15,15,0.14)" }}
          >
            {chip}
            <button
              type="button"
              aria-label={`Remove ${chip}`}
              onClick={() =>
                setRemoved((prev) => {
                  const next = new Set(prev);
                  next.add(chip);
                  return next;
                })
              }
              className="text-ink-3 hover:text-ink leading-none"
            >
              ×
            </button>
          </span>
        ))}

      <Link
        href="/start"
        className="text-caption text-ink-2 hover:text-ink underline-offset-2 hover:underline ml-1"
      >
        Edit request
      </Link>
    </div>
  );
}
