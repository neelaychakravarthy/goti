// Goti shared contract types. Mirrors api/contracts.py.
// Buyer tool around the deal stack product model — search, compare, approve,
// close, learn.

export type Marketplace = "facebook" | "nextdoor" | "offerup" | "craigslist";

export type RankLabel =
  | "Best leverage"
  | "Best quality"
  | "Fastest pickup"
  | "Backup option";

export interface Seller {
  name: string;
  avatar_initial: string;
  rating?: number;
  sales?: number;
  verified?: boolean;
  reply_speed?: string;
}

export interface ListingPhotos {
  main: string;
  thumbs: string[];
}

export interface Listing {
  id: string;
  title: string;
  marketplace: Marketplace;
  asking_price: number;
  likely_close: number;
  retail_range?: string;
  seller: Seller;
  photos: ListingPhotos;
  location_label: string;
  distance_mi?: number;
  posted_age_days: number;
  pickup_constraint: string;
  condition: string;
  rank_label: RankLabel;
  why_ranked: string;
  note?: string;
  /** Whether this listing is offered for the buyer to select on /compare. */
  selectable?: boolean;
}

/** UI-only state — never serialized to JSON. */
export interface ListingSelection {
  listing: Listing;
  selected: boolean;
}

export type NextMoveKind =
  | "discovery_update"
  | "question"
  | "recommendation"
  | "approval"
  | "seller_reply"
  | "risk_check"
  | "better_offer"
  | "close";

export interface NextMoveItem {
  id: string;
  kind: NextMoveKind;
  title: string;
  body: string;
  action_label?: string;
  action_href?: string;
  timestamp?: string;
}

export interface DiscoveryStage {
  t_ms: number;
  status_text: string;
  /** Listing id that appears at this stage, if any. */
  appears_listing_id?: string;
}

export interface BuyingBrief {
  item: string;
  max_price: number;
  near: string;
  avoid: string;
  pickup_timing: string;
}

export interface MarketplaceChannel {
  marketplace: Marketplace;
  name: string;
  status: "messages ready" | "search only";
  state: "connected" | "available";
}

export type ApprovalStatus =
  | "waiting"
  | "selected"
  | "needs_edit"
  | "lower_priority";

export interface ApprovalTicket {
  id: string;
  recipient_name: string;
  marketplace: Marketplace;
  listing_title: string;
  ask_price: number;
  draft_text: string;
  why_text: string;
  expected_outcome: string;
  status: ApprovalStatus;
  selected: boolean;
  /** AgentField-emitted id for the approval (e.g. `job-<id>-msg-<n>`).
   * When present, the approve button posts to /api/approvals/{this id}
   * to drive the pause/resume bridge. */
  approval_request_id?: string | null;
  /** Foreign keys back to the originating hunt / job — set by the
   * backend when the approval is bound to a Job row. */
  hunt_id?: string | null;
  job_id?: string | null;
  /** Server-side ``Job.status`` for the parent job (when bound). The
   * /approve page surfaces a "Check for reply" CTA when this equals
   * ``"awaiting_seller_reply"``. */
  job_status?: string | null;
  listing_id?: string | null;
}

export interface Outbox {
  sent: number;
  drafts: number;
  waiting: number;
  selected: number;
  skipped: number;
}

export interface PriceLadder {
  your_max: number;
  seller_asks: number;
  goti_recommends: number;
  competing_seller: number;
}

export interface SavingsReceipt {
  pay: number;
  save_vs_asking: number;
  under_budget: number;
}

export interface NextMove {
  job_id: string;
  headline: string;
  sub: string;
  price_ladder: PriceLadder;
  plain_english: string;
  savings: SavingsReceipt;
  draft: string;
  /** AgentField id for the pending approval row backing ``draft``.
   *  Null while the negotiator is still drafting async, or after the
   *  draft has been resolved (approved/rejected). */
  approval_request_id?: string | null;
  /** Reasoner-provided justification for the draft. */
  draft_reasoning?: string | null;
  listing_summary?: string;
  seller_check?: SellerCheck;
  /** Phase E readiness signal from the classifier reasoner. When True,
   * the deal page surfaces a "Ready to close" badge that opens the
   * finalize-close modal. */
  ready_to_close?: boolean;
  close_signal_reason?: string | null;
  suggested_close_price?: number | null;
}

export interface SellerCheck {
  history: string;
  location: string;
  risk: string;
}

export type ConversationFrom = "seller" | "goti_draft";
export type ConversationStatus = "sent" | "draft_saved_not_sent";

export interface ConversationMessage {
  from: ConversationFrom;
  speaker?: string;
  at: string;
  text: string;
  status: ConversationStatus;
}

export interface DealRoom {
  job_id: string;
  /** Server-side ``Job.status``. The deal page reads this to decide
   * whether to render the "Check for reply from seller" CTA (shown only
   * when ``"awaiting_seller_reply"``). */
  job_status?: string | null;
  listing: Listing;
  seller_check: SellerCheck;
  conversation: ConversationMessage[];
  safety_banner_after: string;
  next_move: NextMove;
}

// Legacy shape kept simple for routes that still expose Jobs.
export type JobStatus =
  | "active"
  | "awaiting_approval"
  | "awaiting_reply"
  | "closed"
  | "declined";

export interface Job {
  job_id: string;
  listing_id: string;
  title: string;
  marketplace: Marketplace;
  status: JobStatus;
  last_event_at: string;
}

export type MessageDirection = "outbound" | "inbound";
export type MessageStatus = "sent" | "pending_approval" | "rejected" | "received";

export interface Message {
  message_id: string;
  job_id: string;
  direction: MessageDirection;
  text: string;
  sent_at: string;
  status: MessageStatus;
}

export interface LearningNote {
  kind: "message_tactic" | "local_price_memory" | "trust_signal";
  title: string;
  body: string;
}

export interface Case {
  case_id: string;
  title: string;
  location: string;
  start_price: number;
  closed_price: number;
  saved: number;
  tactic_learned: string;
  seller_pattern: string;
  learning_attached?: string;
}

export interface NewLearning {
  body: string;
}

export interface Playbook {
  cases: Case[];
  notes: LearningNote[];
  new_learning: NewLearning;
}

export type ApprovalDecision =
  | "approve"
  | "reject"
  | "edit"
  | "skip"
  | "close_deal";

// Notification + Hunt lifecycle shapes — mirrors api/models.py::Notification /
// Hunt. Source of truth lives on the backend; this file mirrors the JSON-over-
// SSE payload shape returned by GET/POST /api/notifications and
// GET /api/hunts.

export type NotificationKind =
  | "clarifying_question"
  | "listings_found"
  | "approval_needed"
  | "seller_replied"
  | "deal_closed"
  | "error"
  | "info";

export type NotificationStatus = "unread" | "read" | "resolved" | "dismissed";

export interface Notification {
  id: string;
  user_id: string;
  hunt_id?: string | null;
  job_id?: string | null;
  kind: NotificationKind;
  title: string;
  body: string;
  /** Kind-specific structured payload (e.g. `{question}` for clarifying_question,
   * `{draft_text}` for approval_needed). */
  payload: Record<string, unknown>;
  /** Where the UI should navigate when this notification is clicked. */
  target_href: string;
  approval_request_id?: string | null;
  status: NotificationStatus;
  created_at: string;
  read_at?: string | null;
  resolved_at?: string | null;
}

export type HuntStatus =
  | "awaiting_clarification"
  | "discovering"
  | "awaiting_picks"
  | "negotiating"
  | "paused"
  | "closed"
  | "error";

// Granular lifecycle phase (mirrors api/models.py::Hunt.lifecycle_phase).
// Used by the resumption-aware backend; frontend can surface it for
// debugging UIs without changing the user-facing ``status`` copy.
export type HuntLifecyclePhase =
  | "clarifying"
  | "discovering"
  | "valuing"
  | "picking"
  | "negotiating"
  | "closed"
  | "error";

export interface IntegrationAccount {
  provider: "fb" | "nextdoor" | "offerup" | "craigslist";
  linked: boolean;
  linked_at?: string | null;
  /** Browserbase Live View URL for in-progress (pending) links. The
   * frontend can re-open the login tab without re-minting a session
   * when the user accidentally closed it. */
  live_view_url?: string | null;
}

export interface UserProfile {
  id: string;
  email: string;
  name?: string | null;
  picture?: string | null;
  location?: string | null;
  onboarding_completed: boolean;
  integrations: IntegrationAccount[];
  /** ISO-8601 timestamp of the user row's `created_at`. */
  member_since?: string | null;
  /** Derived field: "linked" if any integration row is active, otherwise "not linked". */
  marketplaces_status?: "linked" | "not linked";
}

export interface HuntState {
  id: string;
  user_id: string;
  goal_text: string;
  brief?: Record<string, unknown> | null;
  budget?: number | null;
  status: HuntStatus;
  /** Granular phase (more precise than ``status``). */
  lifecycle_phase?: HuntLifecyclePhase;
  created_at: string;
  updated_at: string;
  // Derived counts surfaced on GET /api/hunts/{id} + GET /api/hunts/active.
  // Older /api/hunts list response omits these for cheapness — treat as
  // optional so existing call-sites don't break.
  candidates_count?: number;
  open_negotiations_count?: number;
  /** Jobs sitting in ``awaiting_seller_reply``. Surfaced separately so the
   * HuntStatusBar can prompt "click to check for replies". */
  awaiting_reply_count?: number;
  pending_hitl_count?: number;
  last_activity_at?: string | null;
  /** Phase T — per-tab unresolved-item counts keyed by job_id. Empty
   * object when nothing on any tab needs attention. */
  tab_badges?: Record<string, number>;
}

/** Per-step browser-agent reasoning event — drives the live "what is
 * Goti doing right now" timeline on the hunt detail page. Mirrors
 * api/contracts.py::HuntActivityEvent. */
export interface HuntActivityEvent {
  id: string;
  hunt_id: string;
  job_id?: string | null;
  /** Free-form phase label: `discovery` / `send_message` / `fetch_replies` /
   * `listing_discovered` / `task_started` / `task_completed` / `task_errored` /
   * `analyzer_progress` / `analyzer_complete` / `approval_queued` / `reasoning`. */
  phase: string;
  step_idx: number;
  thinking?: string | null;
  next_goal?: string | null;
  /** Short human-readable summary of the action taken at this step. */
  action_summary?: string | null;
  url?: string | null;
  created_at?: string | null;
}

// ---------------------------------------------------------------------------
// Memory page — per-Case detail view (analyzer JSON content + user notes)
// ---------------------------------------------------------------------------

/** Structured per-negotiation analysis written by the analyzer reasoner.
 * Mirrors the JSON content blob stored as the EverOS Case's message body. */
export interface CaseAnalyzerPayload {
  what_worked?: string[];
  what_didnt?: string[];
  key_moments?: Array<{ turn_idx: number; observation: string }>;
  tactical_lessons?: string[];
  category?: string;
  region?: string;
  confidence?: number;
  outcome?: string;
}

/** Combined response shape for ``GET /api/memory/cases/{id}``. */
export interface CaseDetail {
  case: Case & {
    /** Backwards-compat — older shapes had only ``id`` and ``user_id``;
     * the new contract surfaces all of ``Case``. */
    id: string;
    user_id: string;
    title: string;
    summary: string;
    outcome?: string | null;
    final_price?: number | null;
    category?: string | null;
    region?: string | null;
    created_at: string;
  };
  analyzer: CaseAnalyzerPayload | null;
  notes_text: string;
}

/** Internal Case shape mirroring api/contracts.py::Case (different from
 * the legacy ``Case`` above which is the StreamACase Memory variant —
 * yes we have two; that's pre-existing). The new memory page consumes
 * this shape via ``GET /api/memory/cases``. */
export interface MemoryCase {
  id: string;
  user_id: string;
  title: string;
  summary: string;
  outcome?: string | null;
  final_price?: number | null;
  category?: string | null;
  region?: string | null;
  created_at: string;
}

/** Skill shape — mirrors api/contracts.py::Skill. */
export interface MemorySkill {
  id: string;
  name: string;
  description: string;
  category?: string | null;
  region?: string | null;
  derived_from_case_ids: string[];
  created_at: string;
}

// ---------------------------------------------------------------------------
// Inbox panel — aggregate cross-hunt items needing user attention
// ---------------------------------------------------------------------------

export type InboxItemKind = "approval" | "ready_to_close";

export interface InboxItem {
  kind: InboxItemKind;
  hunt_id?: string | null;
  hunt_title?: string | null;
  job_id?: string | null;
  approval_request_id?: string | null;
  label: string;
  target_href: string;
  created_at?: string | null;
}

export interface InboxResponse {
  items: InboxItem[];
  total: number;
}

// ---------------------------------------------------------------------------
// Running tasks — Phase L observability registry
// ---------------------------------------------------------------------------

export interface RunningTask {
  task_id: string;
  kind: string;
  hunt_id?: string | null;
  job_id?: string | null;
  label: string;
  started_at?: string | null;
  elapsed_s: number;
}

export interface RunningTasksResponse {
  tasks: RunningTask[];
}

// ---------------------------------------------------------------------------
// Phase O — durable async tasks. Persisted via the `async_tasks` table.
// ---------------------------------------------------------------------------

/** A task row left ``interrupted`` by a process restart — surfaces in
 *  the chat-first task strip with a per-row Resume button. */
export interface StoppedTask {
  id: string;
  kind: string;
  label: string;
  user_id: string;
  hunt_id?: string | null;
  job_id?: string | null;
  status: string;
  summary?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  resume_payload?: Record<string, unknown> | null;
  /** False for kinds we can't auto-resume (check_replies, finalize_close).
   * The UI hides the Resume button in that case. */
  can_resume: boolean;
}

export interface StoppedTasksResponse {
  tasks: StoppedTask[];
}

/** Response shape for ``POST /api/tasks/{task_id}/resume``. */
export interface ResumeTaskResponse {
  ok: boolean;
  old_task_id: string;
  new_task_id: string;
  status: "resuming";
}
