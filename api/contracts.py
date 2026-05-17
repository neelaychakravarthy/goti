"""Shared Pydantic types — the backend-frontend REST contract.

These shapes are mirrored in `web/types.ts`. Changes here require a
matching update on the frontend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, NewType

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Discovery


class Listing(BaseModel):
    """A single listing surfaced by the discovery layer."""

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    price: float
    marketplace: Literal["fb", "nextdoor", "offerup", "craigslist"]
    url: str
    image_url: str | None = None
    seller_name: str | None = None
    location: str | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# Negotiation / job state


class Message(BaseModel):
    """One message in a negotiation thread (either side)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    job_id: str
    role: Literal["seller", "buyer_agent", "system"]
    text: str
    sent_at: datetime


class ApprovalCard(BaseModel):
    """A draft awaiting human approval before Actionbook dispatches it."""

    model_config = ConfigDict(extra="ignore")

    id: str
    job_id: str
    draft_text: str
    draft_reasoning: str | None = None
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime


class Job(BaseModel):
    """A long-running negotiation against one listing."""

    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    listing_id: str
    status: Literal[
        "draft",
        "active",
        "awaiting_approval",
        "awaiting_seller_reply",
        "awaiting_user_approval",
        "closed",
        "cancelled",
    ]
    target_price: float | None = None
    listing: Listing | None = None
    messages: list[Message] = Field(default_factory=list)
    pending_approval_card: ApprovalCard | None = None
    created_at: datetime
    last_message_at: datetime | None = None


# ---------------------------------------------------------------------------
# Memory (EverOS)


class Case(BaseModel):
    """A completed negotiation persisted to EverOS, surfaced in the Memory Bank."""

    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    title: str
    summary: str
    outcome: Literal["closed_deal", "abandoned", "no_response"] | None = None
    final_price: float | None = None
    category: str | None = None
    region: str | None = None
    created_at: datetime


class Skill(BaseModel):
    """An EverOS-extracted negotiation pattern (by category + region)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str
    category: str | None = None
    region: str | None = None
    derived_from_case_ids: list[str] = Field(default_factory=list)
    created_at: datetime


# ---------------------------------------------------------------------------
# Integrations


class IntegrationAccount(BaseModel):
    """A linked external marketplace (FB Marketplace, Nextdoor, OfferUp,
    Craigslist) for the user."""

    model_config = ConfigDict(extra="ignore")

    provider: Literal["fb", "nextdoor", "offerup", "craigslist"]
    linked: bool = False
    linked_at: datetime | None = None
    # Browserbase Live View URL for in-progress (status="pending") links —
    # the frontend can re-open the login tab without minting a fresh
    # session when the user accidentally closed it.
    live_view_url: str | None = None


# ---------------------------------------------------------------------------
# User profile (Google OAuth sign-in)


class UserProfile(BaseModel):
    """The current user's profile + onboarding state.

    Returned by ``GET /api/me``. ``integrations`` is denormalised here
    so the onboarding checklist can render in a single request.

    ``member_since`` is the user row's ``created_at`` (ISO-8601 string)
    surfaced for the /account page. ``marketplaces_status`` is a derived
    summary — ``"linked"`` if any integration row has ``status="active"``,
    otherwise ``"not linked"``.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    email: str
    name: str | None = None
    picture: str | None = None
    location: str | None = None
    onboarding_completed: bool = False
    integrations: list[IntegrationAccount] = Field(default_factory=list)
    member_since: str | None = None
    marketplaces_status: Literal["linked", "not linked"] = "not linked"


# ---------------------------------------------------------------------------
# Request / response wrappers used by routes


class CreateGoalRequest(BaseModel):
    text: str


class CreateGoalResponse(BaseModel):
    goal_id: str
    clarifying_question: str


class ClarifyRequest(BaseModel):
    budget: float | None = None
    answer: str | None = None


class ClarifyResponse(BaseModel):
    listings: list[Listing]


class ListingsResponse(BaseModel):
    listings: list[Listing]


class NegotiateResponse(BaseModel):
    job_id: str


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "close_deal"]
    edited_text: str | None = None


class ApprovalDecisionResponse(BaseModel):
    ok: bool
    job_id: str
    card_id: str
    decision: Literal["approve", "reject", "close_deal"]


class LinkInitResponse(BaseModel):
    authorize_url: str  # The OAuth provider's authorize URL to redirect the user to.
    state: str          # CSRF/anti-replay token; the callback must echo this back.
    provider: Literal["fb", "nextdoor", "offerup", "craigslist"]


class OAuthCallbackResponse(BaseModel):
    linked: bool
    provider: Literal["fb", "nextdoor", "offerup", "craigslist"]


# ---------------------------------------------------------------------------
# Marketplace driver-level messaging types
#
# Imported by `api/integrations/browser_agent/actions.py`. Distinct from
# `Message` above (which is the REST shape including a UUID `id` +
# `job_id`); `Reply` is the driver-level seller reply shape returned by
# `fetch_replies`.


MessageId = NewType("MessageId", str)


class Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message_id: MessageId
    listing_id: str
    sender: str  # 'seller' | 'system'
    text: str
    received_at: float  # unix ts


# ---------------------------------------------------------------------------
# Frontend UX contract types
#
# Mirror ``web/types.ts`` field-for-field. Field names + nullability match
# the TypeScript shapes verbatim — the TypeScript ``types.ts`` is canonical.
# These coexist alongside the internal ``Listing`` / ``Job`` / etc. types
# above; the rich shapes below are what the frontend consumes via the
# adapter routes in ``api/routes/adapter.py``.


class Seller(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    avatar_initial: str
    rating: float | None = None
    sales: int | None = None
    verified: bool | None = None
    reply_speed: str | None = None


class ListingPhotos(BaseModel):
    model_config = ConfigDict(extra="ignore")

    main: str
    thumbs: list[str] = Field(default_factory=list)


class StreamAListing(BaseModel):
    """Rich listing shape (frontend-facing).

    Distinct from the internal ``Listing`` type above — that one is the
    discovery-layer shape (``price`` float, ``marketplace`` 4-way enum
    with short ``fb`` form). This one carries display-ready fields:
    asking vs. likely-close prices, ranked seller summary, photo refs,
    rank label + reasoning.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    marketplace: Literal["facebook", "nextdoor", "offerup", "craigslist"]
    asking_price: int
    likely_close: int
    retail_range: str | None = None
    seller: Seller
    photos: ListingPhotos
    location_label: str
    distance_mi: float | None = None
    posted_age_days: int
    pickup_constraint: str
    condition: str
    rank_label: Literal[
        "Best leverage", "Best quality", "Fastest pickup", "Backup option"
    ]
    why_ranked: str
    note: str | None = None
    selectable: bool | None = None


class BuyingBrief(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item: str
    max_price: int
    near: str
    avoid: str
    pickup_timing: str


class MarketplaceChannel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    marketplace: Literal["facebook", "nextdoor", "offerup", "craigslist"]
    name: str
    status: Literal["messages ready", "search only"]
    state: Literal["connected", "available"]


class Outbox(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sent: int
    drafts: int
    waiting: int
    selected: int
    skipped: int


class StackPreviewRanked(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    likely_close: int
    marketplace: Literal["facebook", "nextdoor", "offerup", "craigslist"]


class StackPreviewMini(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ranked: list[StackPreviewRanked]
    listings_found: int
    worth_messaging: int
    best_likely_close: str
    messages_sent: int


class ApprovalTicket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    # Explicit AgentField approval_request_id surface so the
    # frontend's /approve handler can post directly to the bridge route.
    # When ``id`` is itself the approval_request_id (DB-backed rows) the
    # two are equal; for fixture-driven rows this stays None.
    approval_request_id: str | None = None
    hunt_id: str | None = None
    job_id: str | None = None
    # Server-side ``Job.status`` for the parent Job (when bound to one).
    # The /approve page reads this to decide whether to render the
    # "Check for reply from seller" CTA next to the existing controls
    # for tickets whose job is in ``"awaiting_seller_reply"``.
    job_status: str | None = None
    listing_id: str | None = None
    recipient_name: str
    marketplace: Literal["facebook", "nextdoor", "offerup", "craigslist"]
    listing_title: str
    ask_price: int
    draft_text: str
    why_text: str
    expected_outcome: str
    status: Literal["waiting", "selected", "needs_edit", "lower_priority"]
    selected: bool


class PriceLadder(BaseModel):
    model_config = ConfigDict(extra="ignore")

    your_max: int
    seller_asks: int
    goti_recommends: int
    competing_seller: int


class SavingsReceipt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pay: int
    save_vs_asking: int
    under_budget: int


class SellerCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    history: str
    location: str
    risk: str


class ConversationMessage(BaseModel):
    """Single message in a deal-room thread.

    ``from`` is a Python reserved word; aliased via ``Field(alias="from")``
    and ``populate_by_name=True`` so both directions (load/dump) honour
    the wire field name.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    from_: Literal["seller", "goti_draft"] = Field(alias="from")
    speaker: str | None = None
    at: str
    text: str
    status: Literal["sent", "draft_saved_not_sent"]


class NextMove(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    headline: str
    sub: str
    price_ladder: PriceLadder
    plain_english: str
    savings: SavingsReceipt
    draft: str
    # AgentField id for the pending approval row backing ``draft``.
    # When None, the negotiator hasn't drafted yet (still running async)
    # or the draft has already been resolved.
    approval_request_id: str | None = None
    # Surfaced separately so the deal page can render the reasoner's
    # justification next to the draft text.
    draft_reasoning: str | None = None
    listing_summary: str | None = None
    seller_check: SellerCheck | None = None
    # Phase E readiness signal — driven by the classifier reasoner.
    # When ``ready_to_close`` is True the UI surfaces a "Ready to close"
    # badge on the deal page; clicking opens the finalize-close modal.
    # ``close_signal_reason`` is the classifier's one-sentence
    # justification; ``suggested_close_price`` is the price both sides
    # appear to have agreed on (null when no agreement detected).
    ready_to_close: bool = False
    close_signal_reason: str | None = None
    suggested_close_price: float | None = None


class DealRoom(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    # Job status — surfaced so the deal page can decide whether to render
    # the "Check for reply from seller" button (which the UI shows only
    # when the job is in ``awaiting_seller_reply``). Mirrors the
    # ``Job.status`` literal set; kept as a free string here so future
    # status additions don't require a contract bump.
    job_status: str | None = None
    listing: StreamAListing
    seller_check: SellerCheck
    conversation: list[ConversationMessage]
    safety_banner_after: str
    next_move: NextMove


class StreamAJob(BaseModel):
    """Simpler ``Job`` shape for the frontend's control-plane list view.

    Distinct from ``Job`` above (the rich internal contract with
    messages + approval card). The list view is intentionally minimal —
    see ``web/types.ts``'s ``Job`` interface.
    """

    model_config = ConfigDict(extra="ignore")

    job_id: str
    listing_id: str
    title: str
    marketplace: Literal["facebook", "nextdoor", "offerup", "craigslist"]
    status: Literal["active", "awaiting_approval", "awaiting_reply", "closed", "declined"]
    last_event_at: str


class LearningNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["message_tactic", "local_price_memory", "trust_signal"]
    title: str
    body: str


class StreamACase(BaseModel):
    """Frontend-facing ``Case`` shape. Distinct from the internal ``Case`` above."""

    model_config = ConfigDict(extra="ignore")

    case_id: str
    title: str
    location: str
    start_price: int
    closed_price: int
    saved: int
    tactic_learned: str
    seller_pattern: str
    learning_attached: str | None = None


class NewLearning(BaseModel):
    model_config = ConfigDict(extra="ignore")

    body: str


class Playbook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cases: list[StreamACase]
    notes: list[LearningNote]
    new_learning: NewLearning


class DiscoveryStage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    t_ms: int
    status_text: str
    appears_listing_id: str | None = None


# ---------------------------------------------------------------------------
# Hunt lifecycle (mirrors web/types.ts::HuntState)
#
# Surfaced by ``GET /api/hunts/{id}`` + ``GET /api/hunts/active``. The list
# endpoint (``GET /api/hunts``) returns the "basic" subset (no derived
# counts) — extra fields are optional so the same model serializes both.


class HuntState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    goal_text: str
    brief: dict | None = None
    budget: float | None = None
    status: Literal[
        "awaiting_clarification",
        "discovering",
        "awaiting_picks",
        "negotiating",
        "closed",
        "error",
    ]
    lifecycle_phase: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    # Derived counts — populated on GET /api/hunts/{id} + GET /api/hunts/active.
    # The cheaper list response (GET /api/hunts) omits these.
    candidates_count: int | None = None
    open_negotiations_count: int | None = None
    awaiting_reply_count: int | None = None
    pending_hitl_count: int | None = None
    last_activity_at: str | None = None


# ---------------------------------------------------------------------------
# Hunt activity (powers GET /api/hunts/{id}/activity — the live reasoning
# timeline in the hunt detail UI).


class HuntActivityEvent(BaseModel):
    """One step of the browser-use Agent loop, surfaced to the UI."""

    model_config = ConfigDict(extra="ignore")

    id: str
    hunt_id: str
    job_id: str | None = None
    phase: str
    step_idx: int
    thinking: str | None = None
    next_goal: str | None = None
    action_summary: str | None = None
    url: str | None = None
    created_at: str | None = None


# ---------------------------------------------------------------------------
# Phase O — persisted async tasks + explicit resume.


class StoppedTask(BaseModel):
    """An async_tasks row left ``interrupted`` by a process restart.

    Surfaced to the chat UI's "Stopped" strip — each entry has a Resume
    button that POSTs to ``/api/tasks/{id}/resume``.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str
    label: str
    user_id: str
    hunt_id: str | None = None
    job_id: str | None = None
    status: str
    summary: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    resume_payload: dict | None = None
    can_resume: bool = True


class ResumeTaskResponse(BaseModel):
    """Response shape for ``POST /api/tasks/{task_id}/resume``."""

    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    old_task_id: str
    new_task_id: str
    status: Literal["resuming"]


# ---------------------------------------------------------------------------
# Phase T — per-tab badge counts on the negotiation tab strip.


class HuntTabBadges(BaseModel):
    """Sub-shape of ``HuntState`` populated by ``GET /api/hunts/{id}``.

    Maps each negotiation tab's ``job_id`` to a count of unresolved
    items: pending approvals + (1 if ready_to_close else 0) +
    (1 if seller message newer than the most-recent buyer_agent
    message else 0).
    """

    model_config = ConfigDict(extra="ignore")

    badges: dict[str, int] = Field(default_factory=dict)
