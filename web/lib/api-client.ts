// Client-side counterpart of lib/api.ts. The server-side helpers use
// `auth()` (Node runtime). Client components must instead read the
// session via the public `/api/auth/session` JSON endpoint and forward
// the Google ID token on each backend call.
//
// Keep this file's exports a strict subset of lib/api.ts's surface —
// only the wrappers used from client components belong here.

import type {
  BuyingBrief,
  CaseDetail,
  DealRoom,
  HuntActivityEvent,
  HuntState,
  InboxResponse,
  Listing,
  MemoryCase,
  MemorySkill,
  ResumeTaskResponse,
  RunningTasksResponse,
  StoppedTasksResponse,
  UserProfile,
} from "@/types";
import { getCachedIdToken } from "@/lib/session-token";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

/**
 * Error thrown on non-2xx responses. Mirrors the server-side ApiError
 * in `lib/api.ts` so client components can branch on `status` for
 * 401/403 → redirect-to-login.
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

async function _idToken(): Promise<string | null> {
  return getCachedIdToken();
}

async function _headers(): Promise<Record<string, string>> {
  const idToken = await _idToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (idToken) headers["Authorization"] = `Bearer ${idToken}`;
  return headers;
}

export async function startHunt(
  text: string,
  brief?: Partial<BuyingBrief>
): Promise<{ ok: true; hunt_id: string; item: string }> {
  const path = "/api/goals";
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: JSON.stringify({ text, ...brief }),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

export async function getHunts(): Promise<HuntState[]> {
  const path = "/api/hunts";
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

export async function getHunt(huntId: string): Promise<HuntState> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

/**
 * Read the live reasoning timeline for a hunt — one row per browser-agent
 * step. Polled every few seconds by the hunt detail UI so the user can
 * watch the agent think.
 */
export async function getHuntActivity(
  huntId: string,
): Promise<HuntActivityEvent[]> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}/activity`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  const body = (await res.json()) as { events?: HuntActivityEvent[] };
  return body.events ?? [];
}

/**
 * Spawn a negotiation Job on a specific candidate. Maps to
 * ``POST /api/hunts/{hunt_id}/jobs``. Idempotent on (hunt_id,
 * listing_id) — if the job already exists, the response carries the
 * existing job_id and ``created: false``.
 */
export async function startNegotiation(
  huntId: string,
  listingId: string,
  targetPrice?: number,
): Promise<{ job_id: string; created: boolean }> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}/jobs`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: JSON.stringify({
      listing_id: listingId,
      ...(targetPrice !== undefined ? { target_price: targetPrice } : {}),
    }),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/** Pause an active hunt — cancels in-flight discovery / negotiation
 * tasks (releasing their Browserbase sessions) and sets the hunt's
 * status to ``paused``. Data is preserved; ``resumeHunt`` picks up
 * where it left off using the cached listings + lifecycle phase. */
export async function pauseHunt(
  huntId: string,
): Promise<{ ok: true; status: string; tasks_cancelled: number }> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}/pause`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/** Resume a paused or errored hunt — re-spawns the lifecycle. The
 * streaming discovery loop rehydrates seen_ids from listings_cache so
 * it skips listings that were already surfaced. */
export async function resumeHunt(
  huntId: string,
): Promise<{ ok: true; status: string }> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}/resume`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/** Stop a hunt — cancels in-flight tasks and marks the hunt closed.
 * Unlike Delete, all data (listings, conversations, activity events)
 * is preserved so the user can review the hunt afterwards. */
export async function stopHunt(
  huntId: string,
): Promise<{ ok: true; status: string; tasks_cancelled: number }> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}/stop`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/**
 * Permanently delete a hunt — cancels in-flight discovery / negotiation
 * tasks, then removes the Hunt, every Job under it, the message
 * threads, approvals, notifications, cached listings, and activity
 * timeline. Backed by ``DELETE /api/hunts/{id}`` on the server.
 */
export async function deleteHunt(
  huntId: string,
): Promise<{ ok: true; tasks_cancelled: number; jobs_deleted: number }> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`DELETE ${path}`, res.status);
  return res.json();
}

export async function getDealStack(huntId: string): Promise<Listing[]> {
  const path = `/api/goals/${encodeURIComponent(huntId)}/listings`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

/**
 * Cached-listing row annotated with the hunt's per-listing Job state.
 *
 * Returned by ``GET /api/hunts/{id}/listings`` and consumed by the
 * Listings tab to split "Discovered" (no ``job_id``) from "Accepted"
 * (``job_id`` present). Fields mirror the discovery-time ``Listing``
 * shape — the backend forwards ``ListingCache.raw_data`` verbatim and
 * annotates with the joined ``Job`` data.
 */
export interface HuntListingEntry {
  id: string;
  title: string;
  price: number;
  marketplace: string;
  url: string;
  description?: string | null;
  image_url?: string | null;
  seller_name?: string | null;
  location?: string | null;
  /** Job.id when this listing has an active or terminal negotiation, else null. */
  job_id?: string | null;
  /** Job.status (active, awaiting_seller_reply, closed, etc.), else null. */
  job_status?: string | null;
}

/**
 * Read the hunt's cached listings, annotated with each listing's Job
 * state. Powers the Listings tab's split between Discovered (no
 * ``job_id``) + Accepted (``job_id`` present). See Phase C of the
 * ancient-brewing-brooks plan.
 */
export async function getHuntListings(
  huntId: string,
): Promise<HuntListingEntry[]> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}/listings`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  const body = (await res.json()) as { listings?: HuntListingEntry[] };
  return body.listings ?? [];
}

export async function submitApprovalDecision(
  approvalRequestId: string,
  decision: "approve" | "reject" | "close_deal",
  feedback?: Record<string, unknown> | string | number,
  editedText?: string
): Promise<{ ok: true }> {
  const path = `/api/approvals/${encodeURIComponent(approvalRequestId)}`;
  const payload: Record<string, unknown> = { decision, feedback };
  if (typeof editedText === "string") payload.edited_text = editedText;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/**
 * Read a single DealRoom by job id. Client-side counterpart of the
 * wrapper in ``lib/api.ts`` — used by the deal page to poll for the
 * negotiator's async draft.
 */
export async function getDealRoom(jobId: string): Promise<DealRoom> {
  const path = `/api/jobs/${encodeURIComponent(jobId)}`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

/**
 * User-triggered seller-reply check. Client-side counterpart of the
 * wrapper in ``lib/api.ts`` — for use from client components.
 */
export async function checkReplies(
  jobId: string
): Promise<{ found: boolean; reply_count?: number; checked_at: string }> {
  const path = `/api/jobs/${encodeURIComponent(jobId)}/check-replies`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: "{}",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/**
 * Trigger the negotiator to draft the next outbound message for a job.
 *
 * Phase D of the ancient-brewing-brooks plan: jobs no longer auto-draft
 * on create. The deal page's "Start negotiating" button calls this
 * endpoint to kick off the first draft; subsequent counter-drafts are
 * spawned automatically by ``check-replies`` after a seller reply.
 */
export async function draftNext(
  jobId: string,
): Promise<{ ok: true; job_id: string; spawned: boolean }> {
  const path = `/api/jobs/${encodeURIComponent(jobId)}/draft-next`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: "{}",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/**
 * Finalize a deal close — sends the yes-message to the chosen seller AND
 * fires decline messages to every sibling job in the same hunt, then
 * marks the hunt closed and writes a Case to EverOS.
 *
 * Phase F of the ancient-brewing-brooks plan. Replaces the old
 * per-approval ``close_deal`` decision for the multi-seller case.
 */
export async function finalizeClose(
  jobId: string,
  finalPrice: number,
  agreedText?: string,
): Promise<{
  ok: true;
  job_id: string;
  hunt_id: string | null;
  siblings_declined: number;
}> {
  const path = `/api/jobs/${encodeURIComponent(jobId)}/finalize-close`;
  const payload: Record<string, unknown> = { final_price: finalPrice };
  if (typeof agreedText === "string" && agreedText.trim().length > 0) {
    payload.agreed_text = agreedText;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/**
 * Fetch the user's most-recently-touched non-terminal hunt. Returns
 * ``null`` when no active hunt exists (the backend replies 204 No
 * Content). Used by the persistent ``HuntStatusBar`` to render the
 * current hunt summary across every authed page.
 */
export async function getActiveHunt(): Promise<HuntState | null> {
  const path = "/api/hunts/active";
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (res.status === 204) return null;
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

// --- /account page wrappers ---

export async function getMe(): Promise<UserProfile> {
  const path = "/api/me";
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

export async function updateLocation(
  location: string
): Promise<{ ok: true; location: string }> {
  const path = "/api/me/location";
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: await _headers(),
    body: JSON.stringify({ location }),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`PATCH ${path}`, res.status);
  return res.json();
}

/**
 * Hard-delete the current user. 204 response → resolves to void. The
 * caller MUST sign-out after this since the session token now points
 * at a missing user.
 */
export async function deleteAccount(): Promise<void> {
  const path = "/api/me";
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`DELETE ${path}`, res.status);
}

/**
 * Marketplace provider — one of the four marketplaces Goti's
 * browser-agent supports. Mirrors `_SUPPORTED_PROVIDERS` on the
 * backend.
 */
export type MarketplaceProvider = "fb" | "nextdoor" | "offerup" | "craigslist";

/**
 * Drop the integration_accounts row for the given provider. Returns
 * ``rows_deleted`` so callers can branch on already-unlinked.
 */
export async function unlinkIntegration(
  provider: MarketplaceProvider
): Promise<{ ok: true; rows_deleted: number }> {
  const path = `/api/integrations/${provider}/unlink`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: "{}",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/**
 * Reset ``onboarding_completed`` to False so the user can re-run the
 * onboarding checklist without losing data.
 */
export async function resetOnboarding(): Promise<{ ok: true }> {
  const path = "/api/me/onboarding/reset";
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: "{}",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/**
 * Stage 1 of the Browserbase Context link flow. Returns the
 * Live View URL the user opens in a new tab to sign into the chosen
 * marketplace. The frontend follows up with ``finishLink`` once the
 * user reports they're done.
 */
export async function linkIntegration(
  provider: MarketplaceProvider
): Promise<{ authorize_url: string; state: string; provider: string }> {
  const path = `/api/integrations/${provider}/link`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: "{}",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

/**
 * Stage 2 of the Browserbase Context link flow. Call after the user
 * confirms they've signed into the relevant marketplace in the Live
 * View tab.
 */
export async function finishLink(
  provider: MarketplaceProvider
): Promise<{ ok: boolean; validated: boolean; error?: string }> {
  const path = `/api/integrations/${provider}/finish`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: "{}",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

// ---------------------------------------------------------------------------
// Phase K — Memory page wrappers
// ---------------------------------------------------------------------------

/** Read every Case for the current user via the EverOS-backed memory route. */
export async function getMemoryCases(): Promise<MemoryCase[]> {
  const path = "/api/memory/cases";
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

/** Read every Skill for the current user (EverOS-extracted patterns). */
export async function getMemorySkills(): Promise<MemorySkill[]> {
  const path = "/api/memory/skills";
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

/** Read one Case + its analyzer JSON payload + the user's custom notes. */
export async function getCaseDetail(caseId: string): Promise<CaseDetail> {
  const path = `/api/memory/cases/${encodeURIComponent(caseId)}`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

/** Upsert the user's free-form notes for a Case. */
export async function updateCaseNotes(
  caseId: string,
  notesText: string,
): Promise<{ ok: true; case_id: string; notes_text: string; updated_at: string | null }> {
  const path = `/api/memory/cases/${encodeURIComponent(caseId)}/notes`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: await _headers(),
    body: JSON.stringify({ notes_text: notesText }),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`PATCH ${path}`, res.status);
  return res.json();
}

/** Delete a Case from EverOS + drop the local notes row. */
export async function deleteCase(
  caseId: string,
): Promise<{ ok: true; case_id: string; everos_deleted: boolean; notes_rows_deleted: number }> {
  const path = `/api/memory/cases/${encodeURIComponent(caseId)}`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`DELETE ${path}`, res.status);
  return res.json();
}

// ---------------------------------------------------------------------------
// Phase L — running tasks
// ---------------------------------------------------------------------------

export async function getRunningTasks(huntId: string): Promise<RunningTasksResponse> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}/running-tasks`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

/** Phase O — read ``interrupted`` async_tasks rows for a hunt so the
 *  chat strip can offer per-row Resume buttons. */
export async function getStoppedTasks(
  huntId: string,
): Promise<StoppedTasksResponse> {
  const path = `/api/hunts/${encodeURIComponent(huntId)}/stopped-tasks`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}

/** Phase O — resume an interrupted task. Returns the new task id (a
 *  fresh ``running`` row) so the strip can optimistically refresh. */
export async function resumeTask(
  taskId: string,
): Promise<ResumeTaskResponse> {
  const path = `/api/tasks/${encodeURIComponent(taskId)}/resume`;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: await _headers(),
    body: "{}",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`POST ${path}`, res.status);
  return res.json();
}

// ---------------------------------------------------------------------------
// Phase M — Inbox
// ---------------------------------------------------------------------------

export async function getInbox(): Promise<InboxResponse> {
  const path = "/api/inbox";
  const res = await fetch(`${API_BASE}${path}`, {
    headers: await _headers(),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(`GET ${path}`, res.status);
  return res.json();
}
