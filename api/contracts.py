"""Shared Pydantic types — the A<->B REST contract.

These shapes are mirrored in `web/types.ts` (Stream A). Changes here require
a chat-channel notification per CLAUDE.md "Coordination notes."
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, NewType

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Discovery


class Listing(BaseModel):
    """A single listing surfaced by the discovery layer (Bright Data)."""

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
    """A linked external provider (Facebook Marketplace, Nextdoor) for the user."""

    model_config = ConfigDict(extra="ignore")

    provider: Literal["fb", "nextdoor"]
    linked: bool = False
    linked_at: datetime | None = None


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
    decision: Literal["approve", "reject"]
    edited_text: str | None = None


class ApprovalDecisionResponse(BaseModel):
    ok: bool
    job_id: str
    card_id: str
    decision: Literal["approve", "reject"]


class LinkInitResponse(BaseModel):
    authorize_url: str  # The OAuth provider's authorize URL to redirect the user to.
    state: str          # CSRF/anti-replay token; the callback must echo this back.
    provider: Literal["fb", "nextdoor"]


class OAuthCallbackResponse(BaseModel):
    linked: bool
    provider: Literal["fb", "nextdoor"]


# ---------------------------------------------------------------------------
# Stream C: B↔C messaging types
#
# Imported by `api/integrations/actionbook/{fb,nextdoor}.py` and
# `api/mocks/actionbook.py`. Distinct from `Message` above (which is the
# A↔B REST shape including a UUID `id` + `job_id`); `Reply` is the
# Actionbook-driver-level seller reply shape returned by `fetch_replies`.


MessageId = NewType("MessageId", str)


class Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message_id: MessageId
    listing_id: str
    sender: str  # 'seller' | 'system'
    text: str
    received_at: float  # unix ts
