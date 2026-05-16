// Goti shared contract types. Mirrors api/contracts.py (Stream B will mirror later).
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

export interface BuyingRequest {
  raw_text: string;
  parsed?: BuyingBrief;
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

export interface StackPreviewMini {
  ranked: { title: string; likely_close: number; marketplace: Marketplace }[];
  listings_found: number;
  worth_messaging: number;
  best_likely_close: string;
  messages_sent: number;
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
  listing_summary?: string;
  seller_check?: SellerCheck;
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

export type ApprovalDecision = "approve" | "reject" | "edit" | "skip";
