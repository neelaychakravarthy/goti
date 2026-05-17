// Goti REST contract — server-side fetch wrappers.
//
// Every request carries `Authorization: Bearer <google_id_token>` so the
// backend can verify against Google's JWKS and route to the right User.
// Server components call `auth()` to read the session; client components
// use the sibling `api-client.ts` helper which reads the session via
// `useSession`.

import type {
  ApprovalDecision,
  ApprovalTicket,
  BuyingBrief,
  DealRoom,
  HuntState,
  Listing,
  MarketplaceChannel,
  Notification,
  Outbox,
  Playbook,
  UserProfile,
} from "@/types";

import { auth } from "@/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

function url(path: string): string {
  return `${API_BASE}${path}`;
}

async function _headers(extra?: Record<string, string>): Promise<Record<string, string>> {
  const session = await auth();
  const idToken = (session as { id_token?: string } | null)?.id_token;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(extra ?? {}),
  };
  if (idToken) {
    headers["Authorization"] = `Bearer ${idToken}`;
  }
  return headers;
}

/**
 * Error thrown by every wrapper in this module. The `status` field
 * lets callers branch on auth failures (401/403) for redirect-to-login
 * vs. transient errors that show a Retry button.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  constructor(path: string, status: number, message?: string) {
    super(message ?? `${path} failed: ${status}`);
    this.path = path;
    this.status = status;
  }
}

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = await _headers(init?.headers as Record<string, string> | undefined);
  const res = await fetch(url(path), {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    // Try to pull the backend's ``detail`` field so callers (and the
    // diagnostic surfaces in /onboarding + /account) can show the real
    // exception, not just a bare HTTP code. Failing to parse the body
    // is non-fatal — fall back to the status-only message.
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* response wasn't JSON; ignore */
    }
    throw new ApiError(
      `GET ${path}`,
      res.status,
      detail ? `GET ${path} failed: ${res.status} — ${detail}` : undefined,
    );
  }
  return (await res.json()) as T;
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const headers = await _headers();
  const res = await fetch(url(path), {
    method: "POST",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(`POST ${path}`, res.status);
  }
  return (await res.json()) as T;
}

async function patchJSON<T>(path: string, body?: unknown): Promise<T> {
  const headers = await _headers();
  const res = await fetch(url(path), {
    method: "PATCH",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(`PATCH ${path}`, res.status);
  }
  return (await res.json()) as T;
}

/**
 * Delete with no request body. Backends return 204 No Content on success,
 * so we don't try to parse a body.
 */
async function delJSON(path: string): Promise<void> {
  const headers = await _headers();
  const res = await fetch(url(path), {
    method: "DELETE",
    headers,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(`DELETE ${path}`, res.status);
  }
}

// --- User profile (Google OAuth) ---

export function getMe(): Promise<UserProfile> {
  return getJSON("/api/me");
}

export function completeOnboarding(): Promise<{ ok: true }> {
  return postJSON("/api/me/onboarding/complete", {});
}

export function updateLocation(location: string): Promise<{ ok: true; location: string }> {
  return patchJSON("/api/me/location", { location });
}

/**
 * Hard-delete the current user and all per-user rows (hunts, jobs,
 * messages, approvals, notifications, integrations). 204 → resolves
 * to ``void``. Caller is responsible for following up with
 * ``signOut()`` since the session is now orphaned.
 */
export function deleteAccount(): Promise<void> {
  return delJSON("/api/me");
}

/**
 * Marketplace provider — one of the four marketplaces Goti's
 * browser-agent supports. Mirrors `_SUPPORTED_PROVIDERS` on the
 * backend.
 */
export type MarketplaceProvider = "fb" | "nextdoor" | "offerup" | "craigslist";

/**
 * Drop the integration_accounts row for ``provider`` so the user can
 * re-run the link flow. Returns ``rows_deleted`` so callers can
 * surface "Unlinked X" copy. Idempotent on already-unlinked providers.
 */
export function unlinkIntegration(
  provider: MarketplaceProvider
): Promise<{ ok: true; rows_deleted: number }> {
  return postJSON(`/api/integrations/${provider}/unlink`, {});
}

/**
 * Stage 2 of the Browserbase Context link flow. Call after the user
 * has signed into the relevant marketplace in the Live View tab
 * minted by ``POST /api/integrations/{provider}/link``.
 */
export function finishLink(
  provider: MarketplaceProvider
): Promise<{ ok: true }> {
  return postJSON(`/api/integrations/${provider}/finish`, {});
}

/**
 * Flip ``onboarding_completed`` back to False so the next visit to
 * ``/start`` re-routes the user to ``/onboarding``. Useful for the
 * "redo onboarding without losing data" flow.
 */
export function resetOnboarding(): Promise<{ ok: true }> {
  return postJSON("/api/me/onboarding/reset", {});
}

// --- Search + buying brief ---

export function searchBrief(brief: BuyingBrief): Promise<{ ok: true }> {
  return postJSON("/api/goals", brief);
}

/**
 * Submit a NL goal text (and optional brief fields) to kick off a hunt
 * lifecycle. Returns the `hunt_id` so the frontend can subscribe to
 * lifecycle notifications.
 */
export function startHunt(
  text: string,
  brief?: Partial<BuyingBrief>
): Promise<{ ok: true; hunt_id: string; item: string }> {
  return postJSON("/api/goals", { text, ...brief });
}

/** Read a hunt's current lifecycle state. */
export function getHunt(huntId: string): Promise<HuntState> {
  return getJSON(`/api/hunts/${huntId}`);
}

/**
 * List all hunts for the authenticated user (newest first). The
 * backend filters by the bearer token's user; no user_id query needed.
 */
export function getHunts(): Promise<HuntState[]> {
  return getJSON(`/api/hunts`);
}

export function getBuyingBrief(): Promise<BuyingBrief> {
  return getJSON("/api/buying-brief");
}

export function getMarketplaceChannels(): Promise<MarketplaceChannel[]> {
  return getJSON("/api/channels");
}

// --- Compare (deal stack) ---

/**
 * Fetch the ranked listings for a hunt. Falls back to the legacy `g1` mock
 * goal id when no hunt id is supplied (preserves the pre-notifications
 * standing-desk fixture path).
 */
export function getDealStack(huntId?: string): Promise<Listing[]> {
  const id = huntId && huntId.length > 0 ? huntId : "g1";
  return getJSON(`/api/goals/${encodeURIComponent(id)}/listings`);
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

/**
 * User-triggered seller-reply check. Runs ONE browser-agent fetch
 * against the user's Browserbase context. On a hit, the backend
 * persists the reply, advances the job back to ``active``, and spawns
 * the negotiator to draft a counter (which pauses for approval).
 */
export function checkReplies(
  jobId: string
): Promise<{ found: boolean; reply_count?: number; checked_at: string }> {
  return postJSON(`/api/jobs/${encodeURIComponent(jobId)}/check-replies`, {});
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

// --- Notifications ---

/**
 * Fetch the recent notification inbox for the authenticated user.
 * The backend filters by the bearer token.
 */
export function getNotifications(): Promise<Notification[]> {
  return getJSON(`/api/notifications`);
}

/** Mark a single notification row read (unread -> read). Idempotent. */
export function markNotificationRead(id: string): Promise<{ ok: true }> {
  return postJSON(`/api/notifications/${encodeURIComponent(id)}/read`, {});
}

// --- Approvals (AgentField pause/resume bridge) ---

/**
 * Resolve an approval request by the AgentField `approval_request_id`
 * (e.g. `hunt-<id>-budget`, `hunt-<id>-pick`, `job-<id>-msg-<n>`). The
 * `feedback` payload is kind-specific: a budget number for clarifying
 * questions, a `{picked_listing_ids: string[]}` dict for pick approvals,
 * a `{edited_text: string}` dict for message-draft approvals, a
 * `{final_price: number, agreed_text: string}` dict for the
 * ``close_deal`` decision.
 */
export function submitApprovalDecision(
  approvalRequestId: string,
  decision: "approve" | "reject" | "close_deal",
  feedback?: Record<string, unknown> | string | number
): Promise<{ ok: true }> {
  return postJSON(
    `/api/approvals/${encodeURIComponent(approvalRequestId)}`,
    {
      decision,
      feedback,
    }
  );
}

/**
 * Fetch the user's most-recently-touched non-terminal hunt. Server-side
 * counterpart of the client-side wrapper in ``lib/api-client.ts``.
 * Returns ``null`` on 204 No Content (no active hunt).
 */
export async function getActiveHunt(): Promise<HuntState | null> {
  const path = "/api/hunts/active";
  const headers = await _headers();
  const res = await fetch(url(path), {
    headers,
    cache: "no-store",
  });
  if (res.status === 204) return null;
  if (!res.ok) {
    throw new ApiError(`GET ${path}`, res.status);
  }
  return (await res.json()) as HuntState;
}
