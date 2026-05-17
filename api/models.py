"""SQLAlchemy ORM models for the Goti schema.

Tables:
- ``users`` — Google-OAuth-authenticated multi-tenant users.
- ``integration_accounts`` — Browserbase-Context-linked external
  providers (FB / Nextdoor), keyed off ``str(User.id)``.
- ``hunts`` — long-running buying hunt lifecycles.
- ``jobs`` — per-listing negotiation lifecycles spawned by a hunt.
- ``message_threads`` — per-job message timeline.
- ``approval_queue`` — DB-durable HITL approval rows (paired with
  AgentField's pause/resume bridge).
- ``listings_cache`` — discovery results cached per goal.
- ``notifications`` — user-facing notification stream backing the SSE feed.
- ``hunt_activity_events`` — per-step browser-agent reasoning timeline
  (powers the live "what's it doing" view on the hunt detail page).

CRUD helpers (class-methods) live on each model to keep route code thin.

Note on `users.id` vs `integration_accounts.user_id`: `users.id` is a
UUID PK and `IntegrationAccountRow.user_id` is a free `VARCHAR(255)`
string. We write ``str(User.id)`` into the user_id column so the link
is canonical even without a hard FK; reconciling into a real FK is a
follow-up.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    # Jobs spawned by a Hunt's pick-phase carry the hunt_id back-link
    # so the lifecycle can join job state under its parent hunt. Nullable so
    # legacy ``POST /api/listings/{id}/negotiate`` jobs (no hunt context) still
    # validate.
    hunt_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("hunts.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Final agreed price when the user closes the deal explicitly via the
    # ``"close_deal"`` approval decision (see ``api/routes/approvals.py``).
    # ``NULL`` until the user marks the job closed at a specific price.
    # Replaces the previous heuristic-extraction path (``_extract_agreed_price``)
    # — deterministic user input only.
    final_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Phase E readiness signal — driven by the classifier reasoner
    # (``api/agents/classifier.py``). The classifier auto-invokes after
    # every new message (buyer or seller) and flips ``ready_to_close``
    # to True when the conversation looks like it's reached agreement.
    # The UI surfaces this as a "Ready to close" badge on the deal page;
    # clicking the badge opens the finalize-close modal.
    ready_to_close: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    close_signal_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_close_price: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
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
        hunt_id: Optional[str] = None,
    ) -> "Job":
        """Insert a new Job row, flush, and return the populated row.

        Caller commits.
        """
        row = cls(
            user_id=user_id,
            listing_id=listing_id,
            status=status,
            target_price=target_price,
            hunt_id=hunt_id,
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

    @classmethod
    async def close_at_price(
        cls,
        session: AsyncSession,
        job_id: str,
        final_price: Optional[float],
    ) -> Optional["Job"]:
        """Transition a job to ``closed`` and record the user-confirmed final price.

        Caller commits. Called only from the approval-resolution route when
        the user picks the ``"close_deal"`` decision — never from a heuristic.
        """
        values: dict = {
            "status": "closed",
            "last_message_at": datetime.now(tz=timezone.utc),
        }
        if final_price is not None:
            values["final_price"] = float(final_price)
        await session.execute(
            update(cls).where(cls.id == job_id).values(**values)
        )
        return await cls.get(session, job_id)

    @classmethod
    async def update_readiness(
        cls,
        session: AsyncSession,
        job_id: str,
        *,
        ready_to_close: bool,
        close_signal_reason: Optional[str] = None,
        suggested_close_price: Optional[float] = None,
    ) -> Optional["Job"]:
        """Persist the classifier reasoner's verdict for this job.

        Driven by the classifier reasoner (``api/agents/classifier.py``).
        Caller commits.
        """
        values: dict = {
            "ready_to_close": bool(ready_to_close),
            "close_signal_reason": close_signal_reason,
            "suggested_close_price": (
                float(suggested_close_price)
                if suggested_close_price is not None
                else None
            ),
        }
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

    @classmethod
    async def last_for_job(
        cls, session: AsyncSession, job_id: str
    ) -> Optional["MessageThread"]:
        """Return the most-recent message for ``job_id``, or None if empty.

        Used by ``POST /api/jobs/{job_id}/check-replies`` to compute the
        ``since_ts`` cutoff for the browser-agent ``fetch_replies`` call.
        """
        result = await session.execute(
            select(cls)
            .where(cls.job_id == job_id)
            .order_by(cls.sent_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class ApprovalQueueItem(Base):
    """Approval queue row — the "did the user say yes" record per draft.

    Bridges AgentField's pause/resume primitives to a single DB row that
    drives the full HITL lifecycle:

    - ``approval_request_id`` is the id AgentField uses on its control
      plane (see ``agentfield.client.request_approval``). Frontend uses
      this id as the ``POST /api/approvals/{id}`` path arg.
    - ``execution_id`` is the AgentField execution id that called pause().
    - ``agent_node_id`` is which agent node paused (e.g. ``"goti"``).
    - ``agent_callback_url`` is the agent's own ``/webhooks/approval``
      URL — when the user resolves the approval, FastAPI POSTs to this
      URL so the agent's paused future resumes.
    - ``request_payload`` is what the reasoner included in its
      pause() — used to derive notification kind / title / body.
    """

    __tablename__ = "approval_queue"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    job_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    draft_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    draft_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # approve|reject|None
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # ---- AgentField control-plane bridge columns ----
    execution_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    agent_node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    agent_callback_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_request_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    request_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    feedback: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    job: Mapped[Optional["Job"]] = relationship(back_populates="approval_items")

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        *,
        job_id: Optional[str] = None,
        draft_text: str = "",
        draft_reasoning: Optional[str] = None,
        execution_id: Optional[str] = None,
        agent_node_id: Optional[str] = None,
        agent_callback_url: Optional[str] = None,
        approval_request_id: Optional[str] = None,
        request_payload: Optional[dict] = None,
    ) -> "ApprovalQueueItem":
        row = cls(
            job_id=job_id,
            draft_text=draft_text,
            draft_reasoning=draft_reasoning,
            execution_id=execution_id,
            agent_node_id=agent_node_id,
            agent_callback_url=agent_callback_url,
            approval_request_id=approval_request_id,
            request_payload=request_payload,
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
    async def get_by_approval_request_id(
        cls, session: AsyncSession, approval_request_id: str
    ) -> Optional["ApprovalQueueItem"]:
        """Look up by AgentField's approval_request_id (unique).

        Used by the bridge's request-approval handler (upsert) and by
        the approval-resolution route which receives the approval_request_id
        as the path arg from the frontend.
        """
        result = await session.execute(
            select(cls).where(cls.approval_request_id == approval_request_id)
        )
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
        *,
        feedback: Optional[dict] = None,
    ) -> Optional["ApprovalQueueItem"]:
        """Mark a row as decided ("approve"|"reject"). Caller commits."""
        values: dict = {
            "decision": decision,
            "decided_at": datetime.now(tz=timezone.utc),
        }
        if feedback is not None:
            values["feedback"] = feedback
        await session.execute(
            update(cls).where(cls.id == card_id).values(**values)
        )
        return await cls.get(session, card_id)


class IntegrationAccountRow(Base):
    """Browserbase-Context-linked external account (FB / Nextdoor).

    Goti owns a single ``BROWSERBASE_API_KEY`` + ``BROWSERBASE_PROJECT_ID``;
    each Goti user gets one Browserbase Context
    (``browserbase_context_id``, ``bb_ctx_*``) that persists their
    logged-in browser sessions. A single context covers all marketplaces
    the user logged into inside the Live View session, but we still
    create one row per ``(user_id, provider)`` so the API contract
    (per-provider linked status) stays the same.

    ``live_view_url`` is the Browserbase fullscreen debugger URL the
    user opens in a new tab to sign into marketplaces; persisted so the
    frontend can re-open it on page reload without minting a fresh
    session.
    """

    __tablename__ = "integration_accounts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    browserbase_context_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    live_view_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    # The Browserbase session id behind ``live_view_url``. Stored so
    # ``/finish`` + ``/unlink`` can release the kept-alive session
    # instead of letting it idle until Browserbase times it out.
    live_view_session_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
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

    @classmethod
    async def list_for_user(
        cls, session: AsyncSession, user_id: str
    ) -> list["IntegrationAccountRow"]:
        """Return every row (any status) for the user.

        Differs from ``list_active_for_user`` by including pending rows.
        Used when looking up the user's shared Browserbase Context id —
        any row (pending or active) carries it, since one Context spans
        all marketplaces the user signed into.
        """
        result = await session.execute(
            select(cls).where(cls.user_id == user_id)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Identity + content tables.


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Real multi-tenant user (Google OAuth sign-in).

    One row per real Google account. ``google_sub`` is the immutable
    Google subject id (per OpenID Connect spec); ``email`` is the
    verified email Google returns in the ID token; ``picture`` +
    ``name`` come from Google for the avatar/display surfaces.

    ``location`` + ``onboarding_completed`` drive the post-sign-in
    checklist; ``onboarding_completed=True`` skips the checklist on
    subsequent sign-ins.

    No relationship to ``IntegrationAccountRow`` — that table is keyed
    off a free ``user_id: VARCHAR(255)`` rather than a UUID FK. We
    write the string representation of ``User.id`` into
    ``IntegrationAccountRow.user_id`` for the per-user OAuth flows.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    google_sub: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    picture: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
        server_default=func.now(),
    )

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def get_by_id(
        cls, session: AsyncSession, user_id: "uuid.UUID | str"
    ) -> Optional["User"]:
        if isinstance(user_id, str):
            try:
                user_id = uuid.UUID(user_id)
            except ValueError:
                return None
        result = await session.execute(select(cls).where(cls.id == user_id))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_google_sub(
        cls, session: AsyncSession, google_sub: str
    ) -> Optional["User"]:
        result = await session.execute(
            select(cls).where(cls.google_sub == google_sub)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_email(
        cls, session: AsyncSession, email: str
    ) -> Optional["User"]:
        result = await session.execute(select(cls).where(cls.email == email))
        return result.scalar_one_or_none()

    @classmethod
    async def upsert_from_google(
        cls, session: AsyncSession, claims: dict
    ) -> "User":
        """Insert-or-update a row from Google ID-token claims.

        ``claims`` is the verified payload returned by
        ``google.oauth2.id_token.verify_oauth2_token``. We key on
        ``sub`` (immutable), update ``email`` / ``name`` / ``picture``
        on every sign-in so changes on Google's side propagate, and
        leave ``location`` / ``onboarding_completed`` alone (user-owned).

        Caller commits.
        """
        google_sub = str(claims.get("sub") or "").strip()
        if not google_sub:
            raise ValueError("Google ID-token claims missing 'sub'")
        email = str(claims.get("email") or "").strip().lower()
        name = claims.get("name")
        picture = claims.get("picture")

        existing = await cls.get_by_google_sub(session, google_sub)
        if existing is not None:
            # Refresh mutable fields from Google's latest claims.
            if email and existing.email != email:
                existing.email = email
            if name and existing.name != name:
                existing.name = name
                existing.display_name = name
            if picture and existing.picture != picture:
                existing.picture = picture
            existing.updated_at = datetime.now(timezone.utc)
            await session.flush()
            await session.refresh(existing)
            return existing

        row = cls(
            google_sub=google_sub,
            email=email or f"{google_sub}@unknown.local",
            name=name,
            display_name=name,
            picture=picture,
            onboarding_completed=False,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def update_location(
        cls, session: AsyncSession, user_id: "uuid.UUID | str", location: str
    ) -> Optional["User"]:
        if isinstance(user_id, str):
            try:
                user_id = uuid.UUID(user_id)
            except ValueError:
                return None
        await session.execute(
            update(cls)
            .where(cls.id == user_id)
            .values(location=location, updated_at=datetime.now(timezone.utc))
        )
        return await cls.get_by_id(session, user_id)

    @classmethod
    async def mark_onboarding_complete(
        cls, session: AsyncSession, user_id: "uuid.UUID | str"
    ) -> Optional["User"]:
        if isinstance(user_id, str):
            try:
                user_id = uuid.UUID(user_id)
            except ValueError:
                return None
        await session.execute(
            update(cls)
            .where(cls.id == user_id)
            .values(
                onboarding_completed=True,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return await cls.get_by_id(session, user_id)

    @classmethod
    async def update_onboarding(
        cls,
        session: AsyncSession,
        user_id: "uuid.UUID | str",
        *,
        completed: bool,
    ) -> Optional["User"]:
        """Set ``onboarding_completed`` to ``completed``. Caller commits.

        Used by ``POST /api/me/onboarding/reset`` (sets it back to False
        so the user can re-run the onboarding flow without losing data).
        Mirrors the shape of ``mark_onboarding_complete`` so callers can
        choose between the always-True helper and the explicit setter.
        """
        if isinstance(user_id, str):
            try:
                user_id = uuid.UUID(user_id)
            except ValueError:
                return None
        await session.execute(
            update(cls)
            .where(cls.id == user_id)
            .values(
                onboarding_completed=bool(completed),
                updated_at=datetime.now(timezone.utc),
            )
        )
        return await cls.get_by_id(session, user_id)


class Hunt(Base):
    """A long-running buying hunt — the user's natural-language goal lifecycle.

    Each Hunt drives a multi-phase async coroutine
    (``api/orchestration/hunts.py``):

    1. ``awaiting_clarification`` — clarifier reasoner paused on budget.
    2. ``discovering`` — running discovery + valuation per listing.
    3. ``awaiting_picks`` — pick_listings reasoner paused waiting for the
       user to choose listings.
    4. ``negotiating`` — per-listing negotiation lifecycles in flight.
    5. ``closed`` — all jobs done (or user picked zero listings).
    6. ``error`` — lifecycle raised; see logs.

    The Hunt row is the durable anchor that survives a container restart;
    the ``lifecycle_phase`` column enables phase-by-phase resumption of
    the in-process coroutine on restart.
    """

    __tablename__ = "hunts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    goal_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Parsed BuyingBrief (item, max_price, near, avoid, pickup_timing). Filled
    # once we synthesize structured fields from the goal text (post-budget).
    brief: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    budget: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="awaiting_clarification",
        server_default="awaiting_clarification",
    )
    # Granular phase tracking for durable resumption. The lifecycle
    # coroutine reads this on every restart + skips phases whose work
    # has already been persisted. See
    # ``api/orchestration/hunts.py::run_hunt_lifecycle`` for the
    # phase-by-phase idempotency rules.
    #
    # Values: clarifying | discovering | valuing | picking |
    # negotiating | closed | error.
    lifecycle_phase: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="clarifying",
        server_default="clarifying",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        *,
        user_id: str,
        goal_text: str,
        status: str = "awaiting_clarification",
        lifecycle_phase: str = "clarifying",
        budget: Optional[float] = None,
        brief: Optional[dict] = None,
    ) -> "Hunt":
        row = cls(
            user_id=user_id,
            goal_text=goal_text,
            status=status,
            lifecycle_phase=lifecycle_phase,
            budget=budget,
            brief=brief,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def get(
        cls, session: AsyncSession, hunt_id: str
    ) -> Optional["Hunt"]:
        result = await session.execute(select(cls).where(cls.id == hunt_id))
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_user(
        cls, session: AsyncSession, user_id: str
    ) -> list["Hunt"]:
        result = await session.execute(
            select(cls)
            .where(cls.user_id == user_id)
            .order_by(cls.created_at.desc())
        )
        return list(result.scalars().all())

    # In-flight statuses for ``list_active`` — the set of hunt statuses that
    # represent a lifecycle coroutine the main process expects to be running.
    # On container restart we attempt to resume each one (durable via the
    # ``lifecycle_phase`` column — see ``api/orchestration/hunts.py``).
    _ACTIVE_STATUSES = (
        "awaiting_clarification",
        "discovering",
        "awaiting_picks",
        "negotiating",
    )
    # Same set, expressed in lifecycle_phase terms. The resumption hook
    # uses this — it's more precise than ``status`` (we explicitly
    # include the per-listing ``valuing`` substep + skip terminal phases).
    _ACTIVE_LIFECYCLE_PHASES = (
        "clarifying",
        "discovering",
        "valuing",
        "picking",
        "negotiating",
    )

    @classmethod
    async def list_active(cls, session: AsyncSession) -> list["Hunt"]:
        """Return all hunts whose lifecycle is mid-flight.

        Used by the startup resumption hook to re-spawn lifecycle
        coroutines. Sorted oldest-first so we resume in roughly the
        order they were created.

        Filters on ``lifecycle_phase`` (granular) rather than
        ``status``. Falls back to ``status``-based filter on legacy rows
        whose phase column was just backfilled — both should agree.
        """
        result = await session.execute(
            select(cls)
            .where(cls.lifecycle_phase.in_(cls._ACTIVE_LIFECYCLE_PHASES))
            .order_by(cls.created_at.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def update_status(
        cls, session: AsyncSession, hunt_id: str, new_status: str
    ) -> Optional["Hunt"]:
        await session.execute(
            update(cls)
            .where(cls.id == hunt_id)
            .values(status=new_status, updated_at=datetime.now(tz=timezone.utc))
        )
        return await cls.get(session, hunt_id)

    @classmethod
    async def update_budget(
        cls, session: AsyncSession, hunt_id: str, budget: float
    ) -> Optional["Hunt"]:
        await session.execute(
            update(cls)
            .where(cls.id == hunt_id)
            .values(budget=float(budget), updated_at=datetime.now(tz=timezone.utc))
        )
        return await cls.get(session, hunt_id)

    @classmethod
    async def update_lifecycle_phase(
        cls, session: AsyncSession, hunt_id: str, lifecycle_phase: str
    ) -> Optional["Hunt"]:
        """Advance the internal lifecycle_phase. Caller commits.

        Independent from ``status`` (user-facing copy). Phases must come
        from the set documented on the column.
        """
        await session.execute(
            update(cls)
            .where(cls.id == hunt_id)
            .values(
                lifecycle_phase=lifecycle_phase,
                updated_at=datetime.now(tz=timezone.utc),
            )
        )
        return await cls.get(session, hunt_id)

    @classmethod
    async def set_brief(
        cls, session: AsyncSession, hunt_id: str, brief: dict
    ) -> Optional["Hunt"]:
        await session.execute(
            update(cls)
            .where(cls.id == hunt_id)
            .values(brief=brief, updated_at=datetime.now(tz=timezone.utc))
        )
        return await cls.get(session, hunt_id)


class CaseNotes(Base):
    """User-authored free-form notes attached to one EverOS Case.

    Phase I — Cases themselves live in EverOS (under ``agent_case``);
    this table only stores the buyer's custom annotations so the Memory
    page's per-Case detail view can render an editable notes textarea.
    Keyed by ``case_id`` (the EverOS Case id, free string — not a real
    FK because the Case lives outside our Postgres).
    """

    __tablename__ = "case_notes"

    case_id: Mapped[str] = mapped_column(
        String(255), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    notes_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @classmethod
    async def get(
        cls,
        session: AsyncSession,
        case_id: str,
        user_id: str,
    ) -> Optional["CaseNotes"]:
        """Read the notes row for ``(case_id, user_id)``. Tenant-scoped."""
        result = await session.execute(
            select(cls).where(cls.case_id == case_id, cls.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def upsert(
        cls,
        session: AsyncSession,
        *,
        case_id: str,
        user_id: str,
        notes_text: str,
    ) -> "CaseNotes":
        """Insert or update the notes for a Case. Caller commits."""
        existing = await cls.get(session, case_id, user_id)
        if existing is None:
            row = cls(case_id=case_id, user_id=user_id, notes_text=notes_text)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return row
        existing.notes_text = notes_text
        existing.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await session.refresh(existing)
        return existing

    @classmethod
    async def delete_for_case(
        cls, session: AsyncSession, *, case_id: str, user_id: str
    ) -> int:
        """Delete the notes row(s) matching ``(case_id, user_id)``. Caller commits.

        Returns the number of rows deleted (0 or 1).
        """
        from sqlalchemy import delete as _delete

        result = await session.execute(
            _delete(cls).where(cls.case_id == case_id, cls.user_id == user_id)
        )
        return result.rowcount or 0


class ListingCache(Base):
    """Per-marketplace listing cache populated by the discovery agent.

    `goal_id` is nullable + has no FK because there's no separate
    `goals` table yet — hunts carry the goal text directly. FK gets
    added if a `goals` table lands later.
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
    # No FK — there is no `goals` table yet; hunts carry the goal text
    # directly. FK gets added when a `goals` table lands.
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


# ---------------------------------------------------------------------------
# Notifications.


# Valid `kind` values — kept loose at the column level (free string) so new
# kinds don't need a migration, but the helpers + frontend agree on this set.
NOTIFICATION_KINDS = (
    "clarifying_question",
    "listings_found",
    "approval_needed",
    "seller_replied",
    "deal_closed",
    "error",
    "info",
)

NOTIFICATION_STATUSES = ("unread", "read", "resolved", "dismissed")


class Notification(Base):
    """A user-facing notification.

    Created in two places:

    1. **AgentField bridge** (``api/routes/agent_bridge.py``) when a
       reasoner calls ``app.pause()`` — produces a notification linked
       to an ``ApprovalQueueItem`` via ``approval_request_id``.
    2. **Job orchestration** for non-pause events (listings_found,
       seller_replied, deal_closed).

    Read by:
    - ``GET /api/notifications`` (list)
    - ``GET /api/notifications/stream`` (SSE — drains the in-memory queue
      AND emits a snapshot on connect)
    - ``POST /api/notifications/{id}/read`` (mark a single notification)
    - The approval-resolution route marks the linked notification
      ``resolved`` when the user decides on the underlying approval.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Link back to the parent ``hunts`` row. Free string id; not a FK so
    # other call paths (legacy approvals not tied to a hunt) still validate.
    hunt_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), nullable=True, index=True
    )
    # When the notification is tied to a specific job (e.g. seller_replied,
    # deal_closed), the job_id is denormalised here for cheap filtering.
    job_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), nullable=True
    )
    # One of NOTIFICATION_KINDS; loose at DB level.
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Kind-specific structured data the UI reads (e.g. ``{"question": "..."}``
    # for clarifying_question, ``{"draft_text": "..."}`` for approval_needed).
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Where the UI should navigate when the user clicks the notification.
    target_href: Mapped[str] = mapped_column(String(512), nullable=False, default="/")
    # unread | read | resolved | dismissed
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unread", server_default="unread"
    )
    # When the notification asks for an approval, this is the AgentField
    # approval_request_id that points at the matching ``approval_queue`` row.
    # NOT a FK (approval_queue uses uuid id; this is the AF string id) — the
    # join is done via ``ApprovalQueueItem.approval_request_id``.
    approval_request_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        *,
        user_id: str,
        kind: str,
        title: str,
        body: str = "",
        target_href: str = "/",
        payload: Optional[dict] = None,
        hunt_id: Optional[str] = None,
        job_id: Optional[str] = None,
        approval_request_id: Optional[str] = None,
        status: str = "unread",
    ) -> "Notification":
        row = cls(
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            target_href=target_href,
            payload=payload or {},
            hunt_id=hunt_id,
            job_id=job_id,
            approval_request_id=approval_request_id,
            status=status,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def get(
        cls, session: AsyncSession, notification_id: str
    ) -> Optional["Notification"]:
        result = await session.execute(select(cls).where(cls.id == notification_id))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_approval_request_id(
        cls, session: AsyncSession, approval_request_id: str
    ) -> Optional["Notification"]:
        result = await session.execute(
            select(cls).where(cls.approval_request_id == approval_request_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_user(
        cls,
        session: AsyncSession,
        user_id: str,
        *,
        statuses: Optional[list[str]] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> list["Notification"]:
        """Return notifications for ``user_id`` ordered by created_at DESC.

        ``statuses`` filters to specific status values (e.g.
        ``["unread", "read"]``). ``since`` filters to rows created at-or-after
        the given timestamp.
        """
        stmt = select(cls).where(cls.user_id == user_id)
        if statuses:
            stmt = stmt.where(cls.status.in_(statuses))
        if since is not None:
            stmt = stmt.where(cls.created_at >= since)
        stmt = stmt.order_by(cls.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def list_unread_for_user(
        cls,
        session: AsyncSession,
        user_id: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> list["Notification"]:
        return await cls.list_for_user(
            session,
            user_id,
            statuses=["unread"],
            since=since,
            limit=limit,
        )

    @classmethod
    async def mark_read(
        cls, session: AsyncSession, notification_id: str
    ) -> Optional["Notification"]:
        """Transition unread → read. Idempotent on already-read rows.

        Does NOT transition rows that are already ``resolved`` or
        ``dismissed`` — those are terminal.
        """
        await session.execute(
            update(cls)
            .where(
                cls.id == notification_id,
                cls.status.in_(["unread", "read"]),
            )
            .values(status="read", read_at=datetime.now(tz=timezone.utc))
        )
        return await cls.get(session, notification_id)

    @classmethod
    async def mark_resolved(
        cls, session: AsyncSession, notification_id: str
    ) -> Optional["Notification"]:
        """Terminal transition. Used when the underlying approval was decided."""
        await session.execute(
            update(cls)
            .where(cls.id == notification_id)
            .values(
                status="resolved",
                resolved_at=datetime.now(tz=timezone.utc),
            )
        )
        return await cls.get(session, notification_id)

    @classmethod
    async def mark_dismissed(
        cls, session: AsyncSession, notification_id: str
    ) -> Optional["Notification"]:
        await session.execute(
            update(cls)
            .where(cls.id == notification_id)
            .values(status="dismissed")
        )
        return await cls.get(session, notification_id)

    def to_event_dict(self) -> dict:
        """Serialize for SSE / JSON list responses.

        ISO timestamps + a small status helper. Kept on the model so
        the SSE generator + list route share one definition.
        """
        return {
            "id": self.id,
            "user_id": self.user_id,
            "hunt_id": self.hunt_id,
            "job_id": self.job_id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "payload": dict(self.payload or {}),
            "target_href": self.target_href,
            "status": self.status,
            "approval_request_id": self.approval_request_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


# ---------------------------------------------------------------------------
# Hunt activity events — per-step reasoning timeline.


class HuntActivityEvent(Base):
    """One step of the ``browser-use`` Agent loop.

    Captures what the LLM was thinking, the next sub-goal it set, and a
    short human-readable summary of the action it took. Surfaced as a
    live timeline in the hunt detail UI so the user can watch the agent
    reason through discovery and negotiation.

    Hunt-scoped (always carries ``hunt_id``). ``job_id`` is populated
    when the step ran inside a per-job action (``send_message`` /
    ``fetch_replies``); discovery steps leave it null.
    """

    __tablename__ = "hunt_activity_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    hunt_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("hunts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Free-form phase label — ``discovery`` / ``send_message`` /
    # ``fetch_replies``. Stored as a string so adding a new phase
    # doesn't need a migration.
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    step_idx: Mapped[int] = mapped_column(nullable=False)
    thinking: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_hunt_activity_events_hunt_created",
            "hunt_id",
            "created_at",
        ),
    )

    @classmethod
    async def insert(
        cls,
        session: AsyncSession,
        *,
        hunt_id: str,
        phase: str,
        step_idx: int,
        thinking: Optional[str] = None,
        next_goal: Optional[str] = None,
        action_summary: Optional[str] = None,
        url: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> "HuntActivityEvent":
        row = cls(
            hunt_id=hunt_id,
            job_id=job_id,
            phase=phase,
            step_idx=step_idx,
            thinking=thinking,
            next_goal=next_goal,
            action_summary=action_summary,
            url=url,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    @classmethod
    async def list_for_hunt(
        cls,
        session: AsyncSession,
        hunt_id: str,
        *,
        limit: int = 200,
    ) -> list["HuntActivityEvent"]:
        """Oldest-first so the UI can append-only without re-sorting."""
        stmt = (
            select(cls)
            .where(cls.hunt_id == hunt_id)
            .order_by(cls.created_at.asc(), cls.step_idx.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "hunt_id": self.hunt_id,
            "job_id": self.job_id,
            "phase": self.phase,
            "step_idx": self.step_idx,
            "thinking": self.thinking,
            "next_goal": self.next_goal,
            "action_summary": self.action_summary,
            "url": self.url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Async task persistence — Phase O of the followups round.
#
# Backs the in-memory ``_RUNNING_TASKS`` registry in
# ``api/orchestration/tasks.py`` with a durable row per task so the user
# can resume work that was interrupted by a process restart. On startup
# the lifespan hook flips any leftover ``running`` rows to
# ``interrupted``; the chat-first UI lists those via
# ``GET /api/hunts/{id}/stopped-tasks`` with a Resume button per row
# that re-spawns the task via ``POST /api/tasks/{id}/resume``.


class AsyncTaskRow(Base):
    """Durable row for one background task (Phase O).

    Lifecycle:
    - ``start_task`` inserts with ``status='running'``.
    - ``finish_task`` updates to ``status='completed'`` / ``'errored'``
      with ``finished_at=NOW()``.
    - Startup hook flips ``running`` → ``interrupted`` before FastAPI
      accepts requests, so post-crash state is captured.
    - ``POST /api/tasks/{id}/resume`` reads an ``interrupted`` row,
      re-spawns the task with a fresh ``task_id``, and leaves the
      interrupted row in history (so the user sees what was resumed).
    """

    __tablename__ = "async_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    hunt_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    job_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running", server_default="running"
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resume_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # ---------------- CRUD helpers ----------------

    @classmethod
    async def upsert_start(
        cls,
        session: AsyncSession,
        *,
        task_id: str,
        kind: str,
        label: str,
        user_id: str,
        hunt_id: Optional[str] = None,
        job_id: Optional[str] = None,
        resume_payload: Optional[dict] = None,
    ) -> "AsyncTaskRow":
        """Insert (or refresh) a ``running`` row for ``task_id``.

        Idempotent — repeating with the same ``task_id`` just refreshes
        the row's start metadata. Caller commits.
        """
        existing = await session.get(cls, task_id)
        if existing is None:
            row = cls(
                id=task_id,
                kind=kind,
                label=label,
                user_id=user_id,
                hunt_id=hunt_id,
                job_id=job_id,
                status="running",
                resume_payload=resume_payload,
            )
            session.add(row)
            await session.flush()
            return row
        existing.kind = kind
        existing.label = label
        existing.user_id = user_id
        existing.hunt_id = hunt_id
        existing.job_id = job_id
        existing.status = "running"
        existing.summary = None
        existing.finished_at = None
        if resume_payload is not None:
            existing.resume_payload = resume_payload
        await session.flush()
        return existing

    @classmethod
    async def mark_finished(
        cls,
        session: AsyncSession,
        *,
        task_id: str,
        status: str,
        summary: Optional[str] = None,
    ) -> Optional["AsyncTaskRow"]:
        """Update an existing row to a terminal status. Caller commits.

        Silently no-ops if the row doesn't exist (e.g. registry-only
        task in tests that bypassed persistence).
        """
        row = await session.get(cls, task_id)
        if row is None:
            return None
        row.status = status
        row.summary = summary
        row.finished_at = datetime.now(timezone.utc)
        await session.flush()
        return row

    @classmethod
    async def get(
        cls, session: AsyncSession, task_id: str
    ) -> Optional["AsyncTaskRow"]:
        return await session.get(cls, task_id)

    @classmethod
    async def list_interrupted_for_hunt(
        cls,
        session: AsyncSession,
        *,
        hunt_id: str,
        user_id: str,
    ) -> list["AsyncTaskRow"]:
        """Return ``interrupted`` rows for a hunt owned by ``user_id``."""
        stmt = (
            select(cls)
            .where(
                cls.hunt_id == hunt_id,
                cls.user_id == user_id,
                cls.status == "interrupted",
            )
            .order_by(cls.started_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def mark_all_running_interrupted(
        cls, session: AsyncSession
    ) -> int:
        """Flip every ``running`` row to ``interrupted`` (startup hook).

        Caller commits. Returns the number of rows touched.
        """
        result = await session.execute(
            update(cls)
            .where(cls.status == "running")
            .values(
                status="interrupted",
                finished_at=datetime.now(timezone.utc),
            )
        )
        return int(result.rowcount or 0)

    def to_dict(self) -> dict:
        """Serialize for the ``StoppedTask`` REST response."""
        # Resume eligibility per the followups plan: discovery / draft /
        # classifier / analyzer are auto-resumable; check_replies and
        # finalize_close return 409 because the network state may have
        # changed (a half-sent message could re-send).
        can_resume = self.kind in (
            "discovery",
            "draft",
            "negotiator_draft",
            "classifier",
            "analyzer",
        )
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "user_id": self.user_id,
            "hunt_id": self.hunt_id,
            "job_id": self.job_id,
            "status": self.status,
            "summary": self.summary,
            "started_at": (
                self.started_at.isoformat() if self.started_at else None
            ),
            "finished_at": (
                self.finished_at.isoformat() if self.finished_at else None
            ),
            "resume_payload": self.resume_payload,
            "can_resume": can_resume,
        }
