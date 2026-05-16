import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { Marketplace } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPrice(amount: number, currency: string = "USD"): string {
  if (currency === "USD") {
    return `$${amount.toLocaleString("en-US")}`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  const diffMs = now.getTime() - then;
  if (Number.isNaN(diffMs)) return "";

  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hr ago`;
  const day = Math.round(hr / 24);
  if (day < 30) return `${day} day${day === 1 ? "" : "s"} ago`;
  const mo = Math.round(day / 30);
  return `${mo} mo ago`;
}

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

const MARKETPLACE_NAME: Record<Marketplace, string> = {
  facebook: "Facebook Marketplace",
  nextdoor: "Nextdoor",
  offerup: "OfferUp",
  craigslist: "Craigslist",
};

const MARKETPLACE_COLOR: Record<Marketplace, string> = {
  facebook: "var(--mk-facebook)",
  nextdoor: "var(--mk-nextdoor)",
  offerup: "var(--mk-offerup)",
  craigslist: "var(--mk-craigslist)",
};

export function marketplaceLabel(m: Marketplace): string {
  return MARKETPLACE_NAME[m];
}

export function marketplaceColor(m: Marketplace): string {
  return MARKETPLACE_COLOR[m];
}

/**
 * Deterministic photo placeholder palette pick based on a listing id. Returns
 * one of the warm/cool/neutral marketplace photo colorways without rendering
 * anything fake-looking.
 */
const PHOTO_VARIANTS = ["peach", "mint", "neutral"] as const;
export type PhotoVariant = (typeof PHOTO_VARIANTS)[number];

export function photoVariantFor(id: string): PhotoVariant {
  let sum = 0;
  for (let i = 0; i < id.length; i++) sum = (sum + id.charCodeAt(i)) % 997;
  return PHOTO_VARIANTS[sum % PHOTO_VARIANTS.length];
}
