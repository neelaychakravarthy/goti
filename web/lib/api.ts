// NOTE FOR BACKEND HANDOFF:
// Current Stream A pages still import mock JSON / local mock config directly in several places
// (e.g., app/(app)/compare/page.tsx imports @/mocks/listings.json at module scope, and
// app/(app)/search/page.tsx defines LeBron/Couch listings inline).
// Real async backend wiring should either:
//   1. replace those mock imports with these adapter functions, or
//   2. promote this file into the canonical frontend data layer (recommended).
// Do NOT assume changing API endpoints alone will update the UI — page-level refactors required.

// Typed fetch wrappers for the Goti REST contract.
// Default base is "" (same-origin) — Next.js route handlers mock everything in this round.
// When the Stream B Zeabur backend is live, set NEXT_PUBLIC_API_BASE_URL to its URL.

import type {
  ApprovalDecision,
  ApprovalTicket,
  BuyingBrief,
  DealRoom,
  Listing,
  MarketplaceChannel,
  Outbox,
  Playbook,
  StackPreviewMini,
} from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

function url(path: string): string {
  return `${API_BASE}${path}`;
}

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url(path), {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(url(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`POST ${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

// --- Search + buying brief ---

export function searchBrief(brief: BuyingBrief): Promise<{ ok: true }> {
  return postJSON("/api/goals", brief);
}

export function getBuyingBrief(): Promise<BuyingBrief> {
  return getJSON("/api/buying-brief");
}

export function getStackPreview(): Promise<StackPreviewMini> {
  return getJSON("/api/preview");
}

export function getMarketplaceChannels(): Promise<MarketplaceChannel[]> {
  return getJSON("/api/channels");
}

// --- Compare (deal stack) ---

export function getDealStack(): Promise<Listing[]> {
  return getJSON("/api/goals/g1/listings");
}

// --- Approve (outbox) ---

export function getApprovals(): Promise<ApprovalTicket[]> {
  return getJSON("/api/approvals");
}

export function decideApproval(
  id: string,
  decision: ApprovalDecision,
  editedText?: string
): Promise<{ ok: true }> {
  return postJSON(`/api/approvals/${id}`, {
    decision,
    edited_text: editedText,
  });
}

export function getOutbox(): Promise<Outbox> {
  return getJSON("/api/outbox");
}

// --- Deal room ---

export function getDealRoom(jobId: string): Promise<DealRoom> {
  return getJSON(`/api/jobs/${jobId}`);
}

// --- Playbook (memory) ---

export function getPlaybook(): Promise<Playbook> {
  return getJSON("/api/playbook");
}

// --- Marketplace channels (link) ---

export function linkMarketplace(
  provider: "facebook" | "nextdoor" | "offerup" | "craigslist"
): Promise<MarketplaceChannel> {
  return postJSON(`/api/channels/${provider}/link`, {});
}
