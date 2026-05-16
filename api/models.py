"""SQLAlchemy ORM models for the converged Goti schema.

Stream B-owned: jobs, message_threads, approval_queue, integration_accounts.
(Pass 3 moved integration_accounts under Stream B's ownership since Stream B
now owns the full Actionbook OAuth flow end-to-end.)

Stream C-owned: users, listings_cache.

CRUD helpers (class-methods) added in Pass 2 to keep route code thin.

Note on `users.id` vs `integration_accounts.user_id`: `users.id` is a UUID
PK (Stream C's auth surface), but `IntegrationAccountRow.user_id` is a
free `VARCHAR(255)` string keyed off the demo user id (Stream B's OAuth
flow). Reconciling those into a single FK is deferred until the auth
layer + demo-user-id strategy stabilises — tracked in SPEC.md Open
questions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    listing_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list["MessageThread"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    approval_items: Mapped[list["ApprovalQueueItem"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        *,
        user_id: str,
        listing_id: str,
        status: str = "active",
        target_price: Optional[float] = None,
    ) -> "Job":
        """Insert a new Job row, flush, and return the populated row.

        Caller commits.
        """
        row = cls(
            user_id=user_id,
            listing_id=listing_id,
            status=status,
            target_price=target_price,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def get(cls, session: AsyncSession, job_id: str) -> Optional["Job"]:
        result = await session.execute(select(cls).where(cls.id == job_id))
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_user(
        cls, session: AsyncSession, user_id: str
    ) -> list["Job"]:
        result = await session.execute(
            select(cls).where(cls.user_id == user_id).order_by(cls.created_at.desc())
        )
        return list(result.scalars().all())

    @classmethod
    async def advance_status(
        cls,
        session: AsyncSession,
        job_id: str,
        new_status: str,
        *,
        bump_last_message_at: bool = False,
    ) -> Optional["Job"]:
        """Transition status (and optionally bump last_message_at to now).

        Returns the refreshed row, or None if the job doesn't exist.
        """
        values: dict = {"status": new_status}
        if bump_last_message_at:
            values["last_message_at"] = datetime.now(tz=timezone.utc)
        await session.execute(
            update(cls).where(cls.id == job_id).values(**values)
        )
        return await cls.get(session, job_id)


class MessageThread(Base):
    __tablename__ = "message_threads"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # seller | buyer_agent | system
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="messages")

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def append(
        cls,
        session: AsyncSession,
        *,
        job_id: str,
        role: str,
        text: str,
    ) -> "MessageThread":
        row = cls(job_id=job_id, role=role, text=text)
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def list_for_job(
        cls, session: AsyncSession, job_id: str
    ) -> list["MessageThread"]:
        result = await session.execute(
            select(cls).where(cls.job_id == job_id).order_by(cls.sent_at.asc())
        )
        return list(result.scalars().all())


class ApprovalQueueItem(Base):
    __tablename__ = "approval_queue"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    draft_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # approve|reject|None
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="approval_items")

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        *,
        job_id: str,
        draft_text: str,
        draft_reasoning: Optional[str] = None,
    ) -> "ApprovalQueueItem":
        row = cls(
            job_id=job_id,
            draft_text=draft_text,
            draft_reasoning=draft_reasoning,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def get(
        cls, session: AsyncSession, card_id: str
    ) -> Optional["ApprovalQueueItem"]:
        result = await session.execute(select(cls).where(cls.id == card_id))
        return result.scalar_one_or_none()

    @classmethod
    async def get_pending_for_job(
        cls, session: AsyncSession, job_id: str
    ) -> Optional["ApprovalQueueItem"]:
        """Return the newest still-pending (decision IS NULL) row for this job."""
        result = await session.execute(
            select(cls)
            .where(cls.job_id == job_id, cls.decision.is_(None))
            .order_by(cls.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def resolve(
        cls,
        session: AsyncSession,
        card_id: str,
        decision: str,
    ) -> Optional["ApprovalQueueItem"]:
        """Mark a row as decided ("approve"|"reject"). Caller commits."""
        await session.execute(
            update(cls)
            .where(cls.id == card_id)
            .values(decision=decision, decided_at=datetime.now(tz=timezone.utc))
        )
        return await cls.get(session, card_id)


class IntegrationAccountRow(Base):
    """OAuth-linked external account (Actionbook -> FB / Nextdoor).

    Per the Pass-3 "shared OAuth" decision, a single Clerk grant produces
    one row per provider (``fb`` + ``nextdoor``) sharing the same
    ``access_token`` / ``refresh_token`` / ``token_expires_at``. The
    duplication is intentional — it keeps reads cheap (look up by
    ``(user_id, provider)``) while preserving the per-provider linked
    state the SPEC contract expects.
    """

    __tablename__ = "integration_accounts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    actionbook_user_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_integration_user_provider"
        ),
    )

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def upsert(
        cls,
        session: AsyncSession,
        *,
        user_id: str,
        provider: str,
        **fields,
    ) -> "IntegrationAccountRow":
        """Insert or update the row keyed by ``(user_id, provider)``.

        Caller is responsible for committing — keeps batched upserts (e.g.
        the shared-OAuth dual-write) atomic.
        """
        existing = await cls.get(session, user_id, provider)
        if existing is None:
            row = cls(user_id=user_id, provider=provider, **fields)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return row
        for key, value in fields.items():
            setattr(existing, key, value)
        await session.flush()
        await session.refresh(existing)
        return existing

    @classmethod
    async def get(
        cls, session: AsyncSession, user_id: str, provider: str
    ) -> Optional["IntegrationAccountRow"]:
        result = await session.execute(
            select(cls).where(cls.user_id == user_id, cls.provider == provider)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_active_for_user(
        cls, session: AsyncSession, user_id: str
    ) -> list["IntegrationAccountRow"]:
        result = await session.execute(
            select(cls).where(
                cls.user_id == user_id, cls.status == "active"
            )
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Stream C-owned tables.


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """A single-demo-user row (Stream C-owned).

    No relationship to `IntegrationAccountRow` — that table is keyed off a
    free `user_id: VARCHAR(255)` rather than a UUID FK. See module
    docstring for the divergence note.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class ListingCache(Base):
    """Per-marketplace listing cache populated from Bright Data (Stream C).

    `goal_id` is nullable + has no FK because Stream B's `goals` table
    doesn't exist as a separate table yet. FK gets added when that lands.
    """

    __tablename__ = "listings_cache"

    marketplace: Mapped[str] = mapped_column(String(32), nullable=False)
    listing_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # No FK — Stream B owns `goals`. FK gets added when that table lands.
    goal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("marketplace", "listing_id", name="pk_listings_cache"),
        Index("ix_listings_cache_goal_id", "goal_id"),
    )
