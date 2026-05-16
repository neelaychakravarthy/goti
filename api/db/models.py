"""ORM models for Stream C's 3 tables.

Co-owned with Stream B's `jobs`, `message_threads`, `approval_queue`,
`goals` tables — those land on Stream B's branch and merge in later.

- `users` — single demo user for the hackathon; email hardcoded at seed time.
- `integration_accounts` — per-user FB / Nextdoor session refs (one row per
  linked marketplace).
- `listings_cache` — discovery cache keyed by (marketplace, listing_id).
  `goal_id` is nullable + has no FK because the `goals` table is owned by
  Stream B; FK gets added when that table lands.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    integration_accounts: Mapped[list["IntegrationAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class IntegrationAccount(Base):
    __tablename__ = "integration_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # 'fb' | 'nextdoor'
    actionbook_profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Plain JSONB for the demo. SPEC.md follow-up: encrypt before storing
    # real sessions in dev DBs.
    raw_session: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="integration_accounts")

    __table_args__ = (
        Index(
            "ix_integration_accounts_user_provider",
            "user_id",
            "provider",
            unique=True,
        ),
    )


class ListingCache(Base):
    __tablename__ = "listings_cache"

    marketplace: Mapped[str] = mapped_column(String(32), nullable=False)
    listing_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # No FK — Stream B owns `goals`. FK gets added when that table lands.
    goal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("marketplace", "listing_id", name="pk_listings_cache"),
        Index("ix_listings_cache_goal_id", "goal_id"),
    )
