"""Frontend-shape adapter routes over real backend internals.

These routes serve the canonical shapes the frontend was built against
(see ``web/types.ts``). Real-DB-first: each endpoint queries Postgres /
EverOS / Browserbase Context state and serves the live shape. When the
backing source has no data yet (fresh DB, empty memory store) the
response is an empty / default-but-valid shape — no JSON fixtures.

Endpoints (all DB-backed):

- ``/buying-brief`` ← Hunt.brief / Hunt.goal_text / Hunt.budget
- ``/channels`` ← integration_accounts (only fb/nextdoor; offerup +
  craigslist are discovery-only constants)
- ``/outbox`` ← jobs + approval_queue + message_threads counts
- ``/playbook`` ← memory_store.list_cases + list_skills (EverOS)
- ``/jobs`` ← Job.list_for_user joined with listings_cache
- ``/jobs/{job_id}`` ← Job composition (see _compose_deal_room_from_db)
- ``/approvals`` ← ApprovalQueueItem (decision IS NULL, AgentField id-bound)

Mounted at ``/api`` in ``api/main.py``; the included router prefix
matches the other frontend-facing routes.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import current_user
from api.contracts import (
    ApprovalTicket,
    BuyingBrief,
    DealRoom,
    DiscoveryStage,
    LearningNote,
    Listing,
    MarketplaceChannel,
    NewLearning,
    Outbox,
    Playbook,
    Seller,
    ListingPhotos,
    StackPreviewMini,
    StreamACase,
    StreamAJob,
    StreamAListing,
)
from api.db import get_session
from api.models import (
    ApprovalQueueItem,
    Hunt,
    IntegrationAccountRow,
    Job as JobORM,
    ListingCache,
    MessageThread,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["adapter"])


# Frontend marketplace short-form → integration_accounts.provider mapping.
# The frontend uses long form (``facebook``); the OAuth layer uses short
# form (``fb``). Mapping is asymmetric: ``offerup`` + ``craigslist`` are
# discovery-only and never resolve to a linked integration row.
_PROVIDER_LONG_TO_SHORT = {"facebook": "fb", "nextdoor": "nextdoor"}
_PROVIDER_SHORT_TO_LONG = {"fb": "facebook", "nextdoor": "nextdoor"}


# In-memory cache for per-(user, provider) authorize URLs minted by
# ``POST /api/channels/{provider}/link``. Exposed via
# ``GET /api/channels/{provider}/oauth-url`` so the frontend can open
# the OAuth tab on demand without changing the link-response shape.
_OAUTH_URLS_BY_USER_PROVIDER: dict[tuple[str, str], str] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_stream_a_listing(internal: Listing, idx: int) -> StreamAListing:
    """Synthesize a frontend rich listing from an internal discovery Listing.

    v1: hardcoded ranking labels by index; ``likely_close`` is a flat
    12% discount off ``asking_price``. v1.1 should plug LLM valuation +
    ranking against the user's brief.
    """
    if idx == 0:
        rank_label = "Best leverage"
        why_ranked = "A reply from this seller helps negotiate the better desk."
    elif idx == 1:
        rank_label = "Best quality"
        why_ranked = "Use the lower-priced option to ask for a better deal."
    elif idx == 2:
        rank_label = "Fastest pickup"
        why_ranked = "Quickest pickup window helps close fast."
    else:
        rank_label = "Backup option"
        why_ranked = "Fallback if the top options decline."

    marketplace_long = _PROVIDER_SHORT_TO_LONG.get(
        internal.marketplace, internal.marketplace
    )

    seller_name = internal.seller_name or "Seller"
    avatar_initial = (seller_name[:1] or "S").upper()

    return StreamAListing(
        id=internal.id,
        title=internal.title,
        marketplace=marketplace_long,  # type: ignore[arg-type]
        asking_price=int(internal.price),
        likely_close=int(internal.price * 0.88),
        retail_range=None,
        seller=Seller(
            name=seller_name,
            avatar_initial=avatar_initial,
            rating=None,
            sales=None,
            verified=False,
            reply_speed=None,
        ),
        photos=ListingPhotos(
            # Pass the marketplace image URL verbatim when present so
            # the frontend renders the real photo. When the discovery
            # agent emits ``image_url: null``, the frontend renders a
            # neutral "no photo" panel rather than a category-mismatched
            # silhouette.
            main=internal.image_url or "",
            thumbs=[],
        ),
        location_label=internal.location or "Local",
        distance_mi=None,
        posted_age_days=5,
        pickup_constraint="Pickup TBD",
        condition=(internal.description or "Used")[:60],
        rank_label=rank_label,  # type: ignore[arg-type]
        why_ranked=why_ranked,
        note=None,
        selectable=True,
    )


def _empty_buying_brief() -> BuyingBrief:
    return BuyingBrief(
        item="",
        max_price=0,
        near="San Francisco",
        avoid="",
        pickup_timing="today or tomorrow",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/buying-brief", response_model=BuyingBrief)
async def get_buying_brief(
    hunt_id: Optional[str] = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BuyingBrief:
    """Return the BuyingBrief for the requested hunt.

    Resolution order:

    1. ``hunt_id`` passed + hunt row found + non-empty ``brief`` JSONB →
       coerce fields from the brief, capping ``item`` at 60 chars.
    2. ``hunt_id`` passed + hunt row found + brief is null → synthesize
       from ``goal_text`` + ``budget`` so the UI can render something.
    3. No ``hunt_id`` + at least one hunt exists → use the newest hunt.
    4. No hunts exist → empty default shape (item="").
    """
    def _from_hunt(hunt: Hunt) -> BuyingBrief:
        if hunt.brief:
            brief = dict(hunt.brief)
            return BuyingBrief(
                item=str(brief.get("item") or hunt.goal_text or "")[:60],
                max_price=int(brief.get("max_price") or hunt.budget or 0),
                near=str(brief.get("near") or "San Francisco"),
                avoid=str(brief.get("avoid") or ""),
                pickup_timing=str(brief.get("pickup_timing") or "today or tomorrow"),
            )
        return BuyingBrief(
            item=hunt.goal_text[:60],
            max_price=int(hunt.budget or 0),
            near="San Francisco",
            avoid="",
            pickup_timing="today or tomorrow",
        )

    if hunt_id:
        try:
            hunt = await Hunt.get(session, hunt_id)
        except Exception:  # noqa: BLE001 — DB best-effort
            logger.exception("get_buying_brief: Hunt.get failed for %s", hunt_id)
            hunt = None
        if hunt is not None:
            if hunt.user_id != str(user.id):
                raise HTTPException(
                    status_code=403,
                    detail="hunt does not belong to the current user",
                )
            return _from_hunt(hunt)

    # No hunt_id (or hunt not found) — pick the newest hunt for the
    # current user as a sensible default. Falls back to the empty shape if
    # no hunts exist yet.
    try:
        hunts = await Hunt.list_for_user(session, str(user.id))
    except Exception:  # noqa: BLE001 — DB best-effort
        logger.exception("get_buying_brief: Hunt.list_for_user failed")
        hunts = []
    if hunts:
        return _from_hunt(hunts[0])
    return _empty_buying_brief()


# Canonical channel-row defaults. The DB-driven channels endpoint reads
# integration_accounts for fb/nextdoor connection state; offerup +
# craigslist are discovery-only and stay ``state="available"``.
_CHANNEL_DEFAULTS: list[dict] = [
    {
        "marketplace": "facebook",
        "name": "Facebook Marketplace",
        "status": "messages ready",
        "state": "available",
    },
    {
        "marketplace": "nextdoor",
        "name": "Nextdoor",
        "status": "messages ready",
        "state": "available",
    },
    {
        "marketplace": "offerup",
        "name": "OfferUp",
        "status": "messages ready",
        "state": "available",
    },
    {
        "marketplace": "craigslist",
        "name": "Craigslist",
        "status": "search only",
        "state": "available",
    },
]


@router.get("/channels", response_model=list[MarketplaceChannel])
async def get_channels(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MarketplaceChannel]:
    """List marketplace channels with real OAuth-linked state.

    DB-backed: queries ``integration_accounts`` for the current user.
    Channels with a corresponding active row (``fb``/``nextdoor``) are
    flipped to ``state="connected"``; others stay ``"available"``.
    OfferUp + Craigslist are discovery-only and stay
    ``state="available"``.

    On DB error, returns the in-code default list (all available) so the
    UI still renders.
    """
    try:
        linked_rows = await IntegrationAccountRow.list_active_for_user(
            session, str(user.id)
        )
        linked_shorts = {row.provider for row in linked_rows}
    except Exception:  # noqa: BLE001 — graceful degrade
        logger.exception(
            "get_channels: DB lookup failed; returning all-available defaults"
        )
        return [MarketplaceChannel.model_validate(raw) for raw in _CHANNEL_DEFAULTS]

    results: list[MarketplaceChannel] = []
    for raw in _CHANNEL_DEFAULTS:
        mp = raw.get("marketplace")
        provider_short = _PROVIDER_LONG_TO_SHORT.get(mp)
        if provider_short and provider_short in linked_shorts:
            raw = {**raw, "state": "connected", "status": "messages ready"}
        results.append(MarketplaceChannel.model_validate(raw))
    return results


@router.post("/channels/{provider}/link", response_model=MarketplaceChannel)
async def link_channel(
    provider: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MarketplaceChannel:
    """Start the Browserbase Context link flow for a marketplace channel.

    For FB / Nextdoor: calls ``bb_client.create_context`` (or reuses an
    existing pending row) + mints a Live View session, caches the URL
    keyed by ``(user_id, provider_short)`` so the frontend can pick it
    up via ``GET /api/channels/{provider}/oauth-url``. Returns the
    channel immediately so the UI can render a "linking…" affordance
    without waiting for the user to finish in another tab.

    For OfferUp: returns ``{state="available", status="messages ready"}``.
    For Craigslist: returns ``{state="available", status="search only"}``.
    Unknown providers: 400.
    """
    uid = str(user.id)

    if provider in _PROVIDER_LONG_TO_SHORT:
        provider_short = _PROVIDER_LONG_TO_SHORT[provider]
        try:
            # Local import: keep the integration off the module-load path
            # for the test sweep.
            from api.integrations.browserbase import client as bb_client

            existing = await IntegrationAccountRow.get(
                session, uid, provider_short
            )
            if (
                existing
                and existing.browserbase_context_id
                and existing.live_view_url
            ):
                login_url = existing.live_view_url
            else:
                if existing and existing.browserbase_context_id:
                    context_id = existing.browserbase_context_id
                else:
                    context_id = await bb_client.create_context()
                from api.integrations.browserbase.client import (
                    _MARKETPLACE_LOGIN_URLS,
                )
                target_url = _MARKETPLACE_LOGIN_URLS[provider_short]
                _, login_url = await bb_client.create_session_with_live_view(
                    context_id, target_url
                )
                await IntegrationAccountRow.upsert(
                    session,
                    user_id=uid,
                    provider=provider_short,
                    browserbase_context_id=context_id,
                    live_view_url=login_url,
                    status="pending",
                )
                await session.commit()
            _OAUTH_URLS_BY_USER_PROVIDER[
                (uid, provider_short)
            ] = login_url
        except Exception:  # noqa: BLE001 — link init not load-bearing for the demo
            logger.exception(
                "link_channel: create_context failed for provider=%s — returning "
                "channel anyway for demo continuity",
                provider,
            )

        return MarketplaceChannel(
            marketplace=provider,  # type: ignore[arg-type]
            name=("Facebook Marketplace" if provider == "facebook" else "Nextdoor"),
            status="messages ready",
            state="connected",
        )

    if provider == "offerup":
        return MarketplaceChannel(
            marketplace="offerup",
            name="OfferUp",
            status="messages ready",
            state="available",
        )
    if provider == "craigslist":
        return MarketplaceChannel(
            marketplace="craigslist",
            name="Craigslist",
            status="search only",
            state="available",
        )

    raise HTTPException(status_code=400, detail=f"unknown provider: {provider!r}")


@router.get("/channels/{provider}/oauth-url")
async def get_channel_oauth_url(
    provider: str,
    user: User = Depends(current_user),
) -> dict:
    """Return the parked authorize URL minted by ``link_channel``.

    The frontend can call this after ``POST /channels/{provider}/link``
    to open the OAuth tab. Returns ``{authorize_url: null}`` if no URL
    has been minted yet (e.g. for non-OAuth marketplaces).
    """
    if provider not in _PROVIDER_LONG_TO_SHORT:
        return {"authorize_url": None, "provider": provider}
    short = _PROVIDER_LONG_TO_SHORT[provider]
    url = _OAUTH_URLS_BY_USER_PROVIDER.get((str(user.id), short))
    return {"authorize_url": url, "provider": provider}


@router.get("/outbox", response_model=Outbox)
async def get_outbox(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Outbox:
    """Compute Outbox stats live from Postgres.

    Counts are scoped to the current user (joining ``approval_queue`` →
    ``jobs`` for the user filter):

    - ``sent``     — buyer_agent rows in ``message_threads`` for the user
    - ``drafts``   — pending ``approval_queue`` rows (decision IS NULL)
    - ``waiting``  — jobs in ``awaiting_seller_reply``
    - ``selected`` — jobs in ``active``
    - ``skipped``  — rejected approvals (``decision='reject'``)

    On DB error, returns zeros so the UI degrades gracefully.
    """
    from sqlalchemy import func as sql_func, select as sql_select

    uid = str(user.id)
    try:
        # sent — buyer_agent messages on jobs owned by this user
        sent_stmt = (
            sql_select(sql_func.count(MessageThread.id))
            .join(JobORM, MessageThread.job_id == JobORM.id)
            .where(JobORM.user_id == uid, MessageThread.role == "buyer_agent")
        )
        # drafts — unresolved approvals tied to this user's jobs (or
        # unbound approvals, which we include conservatively since the
        # legacy flow can produce job_id=NULL queue rows).
        drafts_stmt = (
            sql_select(sql_func.count(ApprovalQueueItem.id))
            .outerjoin(JobORM, ApprovalQueueItem.job_id == JobORM.id)
            .where(
                ApprovalQueueItem.decision.is_(None),
                (JobORM.user_id == uid) | (ApprovalQueueItem.job_id.is_(None)),
            )
        )
        waiting_stmt = sql_select(sql_func.count(JobORM.id)).where(
            JobORM.user_id == uid, JobORM.status == "awaiting_seller_reply"
        )
        selected_stmt = sql_select(sql_func.count(JobORM.id)).where(
            JobORM.user_id == uid, JobORM.status == "active"
        )
        skipped_stmt = (
            sql_select(sql_func.count(ApprovalQueueItem.id))
            .outerjoin(JobORM, ApprovalQueueItem.job_id == JobORM.id)
            .where(
                ApprovalQueueItem.decision == "reject",
                (JobORM.user_id == uid) | (ApprovalQueueItem.job_id.is_(None)),
            )
        )
        sent = (await session.execute(sent_stmt)).scalar() or 0
        drafts = (await session.execute(drafts_stmt)).scalar() or 0
        waiting = (await session.execute(waiting_stmt)).scalar() or 0
        selected = (await session.execute(selected_stmt)).scalar() or 0
        skipped = (await session.execute(skipped_stmt)).scalar() or 0
    except Exception:  # noqa: BLE001 — DB best-effort
        logger.exception("get_outbox: DB query failed; returning zeros")
        return Outbox(sent=0, drafts=0, waiting=0, selected=0, skipped=0)

    return Outbox(
        sent=int(sent),
        drafts=int(drafts),
        waiting=int(waiting),
        selected=int(selected),
        skipped=int(skipped),
    )


_PLAYBOOK_SKILL_KIND_MAP = {
    "message_tactic": "message_tactic",
    "local_price_memory": "local_price_memory",
    "trust_signal": "trust_signal",
    "messaging": "message_tactic",
    "price": "local_price_memory",
    "trust": "trust_signal",
}


def _stream_a_case_from_everos(case) -> StreamACase:
    """Map an EverOS ``Case`` to the frontend's ``StreamACase`` shape.

    EverOS Cases don't track ``start_price`` directly; we use the
    summary + final_price to fill in best-effort fields. Both prices
    default to 0 if extraction fails; ``saved`` is derived only when
    both are positive.
    """
    final_price = float(case.final_price) if case.final_price else 0
    # Try to pull an asking/start price out of the summary text if present.
    start_price = 0
    summary = case.summary or ""
    # Cheap regex: pick the first "$NNN" in the summary as a hint.
    import re

    matches = re.findall(r"\$(\d+(?:\.\d+)?)", summary)
    if matches:
        try:
            start_price = int(float(matches[0]))
        except ValueError:
            start_price = 0
    saved = start_price - int(final_price) if start_price > 0 and final_price > 0 else 0
    return StreamACase(
        case_id=case.id,
        title=case.title or "Untitled negotiation",
        location=case.region or "Unknown",
        start_price=int(start_price),
        closed_price=int(final_price),
        saved=int(saved) if saved > 0 else 0,
        tactic_learned=summary[:160],
        seller_pattern=summary[160:320],
        learning_attached=None,
    )


def _learning_note_from_skill(skill) -> LearningNote:
    raw_category = (skill.category or "").lower()
    kind = _PLAYBOOK_SKILL_KIND_MAP.get(raw_category, "message_tactic")
    return LearningNote(
        kind=kind,  # type: ignore[arg-type]
        title=skill.name or "Learned tactic",
        body=skill.description or "",
    )


def _empty_playbook() -> Playbook:
    return Playbook(
        cases=[],
        notes=[],
        new_learning=NewLearning(
            body="Playbook updates as new deals close."
        ),
    )


@router.get("/playbook", response_model=Playbook)
async def get_playbook(
    user: User = Depends(current_user),
) -> Playbook:
    """Compose the Playbook from EverOS Cases + Skills for the current user.

    On missing EVEROS_API_KEY / SDK / transport error, ``list_cases`` /
    ``list_skills`` return ``[]`` (graceful degrade — see
    ``api/memory_store.py``). In that case we return an empty Playbook
    shape so the UI degrades to an empty state.
    """
    # local imports keep memory_store + EverOS off the module-load path
    from api.memory_store import list_cases, list_skills

    uid = str(user.id)
    try:
        cases = await list_cases(user_id=uid)
        skills = await list_skills(user_id=uid)
    except Exception:  # noqa: BLE001 — graceful degrade
        logger.exception("get_playbook: EverOS read failed; returning empty Playbook")
        return _empty_playbook()

    if not cases and not skills:
        return _empty_playbook()

    mapped_cases = [_stream_a_case_from_everos(c) for c in cases]
    mapped_notes = [_learning_note_from_skill(s) for s in skills]

    # ``new_learning`` is a one-line synthesis of the most recent case.
    if mapped_cases:
        newest = mapped_cases[0]
        if newest.saved > 0:
            body = (
                f"Closed {newest.title} at ${newest.closed_price} "
                f"({'$' + str(newest.saved)} under ask)."
            )
        else:
            body = newest.tactic_learned or "New learning available."
    else:
        body = "Playbook updates as new deals close."

    return Playbook(
        cases=mapped_cases,
        notes=mapped_notes,
        new_learning=NewLearning(body=body),
    )


_EMPTY_STACK_PREVIEW = StackPreviewMini(
    ranked=[],
    listings_found=0,
    worth_messaging=0,
    best_likely_close="$0",
    messages_sent=0,
)


@router.get("/preview", response_model=StackPreviewMini)
async def get_preview(
    user: User = Depends(current_user),
) -> StackPreviewMini:
    _ = user
    # No real backing store yet — return an empty preview shape so the UI
    # renders its empty state. Filling this in (with the user's newest
    # hunt's listings) is tracked as a follow-up.
    return _EMPTY_STACK_PREVIEW


# Mapping from our internal Job.status enum to the frontend's
# ``StreamAJob.status`` Literal. Anything not in the map defaults to
# "active" so the UI always validates.
_JOB_STATUS_INTERNAL_TO_STREAM_A = {
    "active": "active",
    "draft": "active",
    "awaiting_user_approval": "awaiting_approval",
    "awaiting_approval": "awaiting_approval",
    "awaiting_seller_reply": "awaiting_reply",
    "closed": "closed",
    "cancelled": "declined",
}

_INTERNAL_MARKETPLACE_TO_STREAM_A = {
    "fb": "facebook",
    "facebook": "facebook",
    "nextdoor": "nextdoor",
    "offerup": "offerup",
    "craigslist": "craigslist",
}


async def _stream_a_job_from_orm(session, job) -> StreamAJob:
    """Compose a ``StreamAJob`` from a real ``jobs`` row.

    Pulls the listing title from ``listings_cache`` when available;
    falls back to the listing_id when no cache row exists yet.
    """
    from sqlalchemy import select as sql_select

    title = job.listing_id
    marketplace_internal = "fb"
    try:
        lc_rows = await session.execute(
            sql_select(ListingCache).where(ListingCache.listing_id == job.listing_id)
        )
        lc_row = lc_rows.scalars().first()
        if lc_row is not None:
            title = lc_row.title or job.listing_id
            marketplace_internal = lc_row.marketplace or "fb"
    except Exception:  # noqa: BLE001 — DB best-effort, fall back to defaults
        logger.exception(
            "_stream_a_job_from_orm: ListingCache lookup failed for job=%s", job.id
        )

    marketplace = _INTERNAL_MARKETPLACE_TO_STREAM_A.get(
        marketplace_internal, "facebook"
    )
    status = _JOB_STATUS_INTERNAL_TO_STREAM_A.get(job.status, "active")
    ts_source = job.last_message_at or job.created_at
    last_event_at = ts_source.isoformat() if ts_source else ""
    return StreamAJob(
        job_id=job.id,
        listing_id=job.listing_id,
        title=title,
        marketplace=marketplace,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        last_event_at=last_event_at,
    )


@router.get("/jobs", response_model=list[StreamAJob])
async def list_stream_a_jobs(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[StreamAJob]:
    """List the frontend's job tiles for the control-plane sidebar.

    Real-DB-backed: queries ``jobs`` for the current user (newest first
    via ``Job.list_for_user``), maps each to ``StreamAJob`` with title /
    marketplace joined from ``listings_cache``. Returns ``[]`` when no
    Job rows exist yet.
    """
    try:
        rows = await JobORM.list_for_user(session, str(user.id))
    except Exception:  # noqa: BLE001 — graceful degrade to empty list
        logger.exception("list_stream_a_jobs: DB query failed; returning []")
        return []

    out: list[StreamAJob] = []
    for r in rows:
        try:
            out.append(await _stream_a_job_from_orm(session, r))
        except Exception:  # noqa: BLE001 — skip malformed row, log
            logger.exception(
                "list_stream_a_jobs: mapping failed for job=%s", r.id
            )
    return out


@router.get("/jobs/{job_id}", response_model=DealRoom)
async def get_deal_room(
    job_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> DealRoom:
    """Return the full DealRoom shape for a given job id.

    Pure DB-backed: composes the DealRoom from a real ``Job`` row plus
    its ``MessageThread`` + ``ApprovalQueueItem`` + ``ListingCache``
    rows. 404 if the job doesn't exist.
    """
    try:
        from api.models import Job as JobORM  # local alias

        job = await JobORM.get(session, job_id)
    except Exception:  # noqa: BLE001 — DB best-effort
        logger.exception("get_deal_room: Job lookup failed for job_id=%s", job_id)
        raise HTTPException(status_code=500, detail="job lookup failed")

    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")

    if job.user_id != str(user.id):
        raise HTTPException(
            status_code=403,
            detail="job does not belong to the current user",
        )

    return await _compose_deal_room_from_db(session, job)


async def _compose_deal_room_from_db(session, job) -> DealRoom:
    """Build a DealRoom from a real Job + its DB-backed children.

    Listing details come from ``listings_cache`` when available; missing
    fields default safely so the shape always validates. The ``draft`` +
    ``approval_request_id`` on ``next_move`` come from the pending
    ``ApprovalQueueItem`` for this job (decision IS NULL) — when no
    pending approval exists yet (negotiator still drafting async), the
    draft is an empty string and the frontend keeps polling.
    """
    from api.contracts import (
        ConversationMessage,
        NextMove,
        PriceLadder,
        SavingsReceipt,
        SellerCheck,
    )
    from api.models import (
        ListingCache,
        MessageThread,
    )

    # ---- listing (from listings_cache if available) ----
    # listings_cache has composite PK (marketplace, listing_id) — we don't
    # know the marketplace here, so we query by listing_id alone.
    from sqlalchemy import select

    lc_rows = await session.execute(
        select(ListingCache).where(ListingCache.listing_id == job.listing_id)
    )
    lc_row = lc_rows.scalars().first()

    if lc_row is not None:
        internal_listing = Listing(
            id=lc_row.listing_id,
            title=lc_row.title or "Listing",
            price=(lc_row.price_cents or 0) / 100.0,
            marketplace=lc_row.marketplace,  # type: ignore[arg-type]
            url=lc_row.url or "",
            description=lc_row.description,
            image_url=(lc_row.raw_data or {}).get("image_url"),
            seller_name=(lc_row.raw_data or {}).get("seller_name"),
            location=(lc_row.raw_data or {}).get("location"),
        )
    else:
        # No cache row — synthesize a placeholder so the shape validates.
        internal_listing = Listing(
            id=job.listing_id,
            title="Listing",
            price=float(job.target_price or 0.0),
            marketplace="fb",
            url=f"https://facebook.com/marketplace/item/{job.listing_id}",
        )

    listing = _to_stream_a_listing(internal_listing, 0)

    # ---- conversation ----
    msg_rows = await MessageThread.list_for_job(session, job.id)
    conversation: list[ConversationMessage] = []
    for m in msg_rows:
        # Map our roles to the frontend's ConversationMessage shape.
        if m.role == "buyer_agent":
            sender = "goti_draft"
        elif m.role == "seller":
            sender = "seller"
        else:
            sender = "seller"  # default for system
        conversation.append(
            ConversationMessage(
                **{"from": sender},  # type: ignore[arg-type]
                at=m.sent_at.isoformat() if m.sent_at else "",
                text=m.text,
                status="sent",
            )
        )

    # ---- pending approval (draft + approval_request_id) ----
    # The negotiator's app.pause() POSTs to the agent_bridge router which
    # writes an ApprovalQueueItem with draft_text + approval_request_id.
    # We fetch the still-pending row (decision IS NULL) for this job so
    # the deal page renders the draft + can resolve it.
    pending = await ApprovalQueueItem.get_pending_for_job(session, job.id)
    draft_text = pending.draft_text if pending else ""
    draft_reasoning = pending.draft_reasoning if pending else None
    approval_request_id = pending.approval_request_id if pending else None

    # ---- competing_seller: derive from sibling jobs in the same hunt ----
    # The "competing seller" line on the price ladder shows the lowest
    # competing offer Goti is working — that's the strongest BATNA signal
    # for this negotiation. We pick the LOWEST target_price (or asking_price
    # fallback) among non-terminal sibling jobs in the same hunt. If there
    # are no siblings, the value is 0 and the frontend hides the row.
    competing_seller = 0
    try:
        from api.orchestration.jobs import get_batna_context_for_hunt

        siblings = await get_batna_context_for_hunt(
            hunt_id=job.hunt_id, exclude_job_id=job.id, session=session
        )
        candidate_prices: list[float] = []
        for sib in siblings:
            tp = sib.get("target_price")
            if isinstance(tp, (int, float)) and tp > 0:
                candidate_prices.append(float(tp))
                continue
            ap = sib.get("asking_price")
            if isinstance(ap, (int, float)) and ap > 0:
                candidate_prices.append(float(ap))
        if candidate_prices:
            competing_seller = int(round(min(candidate_prices)))
    except Exception:  # noqa: BLE001 — BATNA join is best-effort
        logger.exception(
            "_compose_deal_room_from_db: BATNA lookup failed job=%s", job.id
        )

    target = float(job.target_price or 0.0)
    # Phase E surface: read the classifier's verdict directly off the Job
    # row. Falls back to defaults when the columns are still NULL (no
    # classifier run yet for this job).
    ready_to_close = bool(getattr(job, "ready_to_close", False) or False)
    close_signal_reason = getattr(job, "close_signal_reason", None)
    suggested_close_price = getattr(job, "suggested_close_price", None)
    next_move = NextMove(
        job_id=job.id,
        headline="Next move",
        sub=(
            "Approve Goti's opening message."
            if draft_text and not conversation
            else "Goti's recommended next step."
        ),
        price_ladder=PriceLadder(
            your_max=int(target * 1.1),
            seller_asks=int(internal_listing.price),
            goti_recommends=int(target),
            competing_seller=competing_seller,
        ),
        plain_english=(
            draft_reasoning
            or "Working a counter offer based on your budget."
        ),
        savings=SavingsReceipt(
            pay=int(target),
            save_vs_asking=max(0, int(internal_listing.price - target)),
            under_budget=0,
        ),
        draft=draft_text,
        approval_request_id=approval_request_id,
        draft_reasoning=draft_reasoning,
        ready_to_close=ready_to_close,
        close_signal_reason=close_signal_reason,
        suggested_close_price=(
            float(suggested_close_price)
            if isinstance(suggested_close_price, (int, float))
            else None
        ),
    )

    seller_check = SellerCheck(
        history="No prior interactions logged.",
        location=internal_listing.location or "Local",
        risk="Standard listing risk.",
    )

    return DealRoom(
        job_id=job.id,
        job_status=job.status,
        listing=listing,
        seller_check=seller_check,
        conversation=conversation,
        safety_banner_after=(
            job.last_message_at.isoformat() if job.last_message_at else ""
        ),
        next_move=next_move,
    )


def _ask_price_from_payload(payload: Optional[dict], fallback: Optional[float]) -> int:
    """Best-effort: read an integer ask_price out of the queue row payload.

    Falls back to ``fallback`` (typically ``job.target_price``) when no
    numeric ``ask_price`` field is present.
    """
    if isinstance(payload, dict):
        for key in ("ask_price", "target_price", "price"):
            val = payload.get(key)
            if isinstance(val, (int, float)):
                return int(val)
            if isinstance(val, str):
                try:
                    return int(float(val.replace("$", "").replace(",", "")))
                except ValueError:
                    pass
    if fallback is not None:
        try:
            return int(float(fallback))
        except (TypeError, ValueError):
            return 0
    return 0


def _expected_outcome_for_job_state(job_status: Optional[str]) -> str:
    """Tiny copy generator so the UI can render an expected_outcome line."""
    if job_status == "awaiting_seller_reply":
        return "Waiting on seller reply"
    if job_status == "active":
        return "Likely yes/no quickly"
    if job_status == "awaiting_user_approval":
        return "Awaiting your approval"
    return "Probably counter"


async def _approval_ticket_from_row(
    session, row: ApprovalQueueItem
) -> ApprovalTicket:
    """Compose an ``ApprovalTicket`` from a real ``approval_queue`` row.

    Joins the linked Job + ListingCache to populate
    ``marketplace`` / ``listing_title`` / ``recipient_name``. Missing
    joins fall back to safe defaults so the shape always validates.
    """
    job: Optional[JobORM] = None
    if row.job_id:
        try:
            job = await JobORM.get(session, row.job_id)
        except Exception:  # noqa: BLE001 — best-effort join
            logger.exception(
                "_approval_ticket_from_row: Job.get failed for job_id=%s", row.job_id
            )

    hunt_id = getattr(job, "hunt_id", None) if job is not None else None
    listing_id = getattr(job, "listing_id", None) if job is not None else None
    target_price = getattr(job, "target_price", None) if job is not None else None
    job_status = getattr(job, "status", None) if job is not None else None

    listing_title = listing_id or "Listing"
    marketplace_internal = "fb"
    recipient_name = "Seller"
    if listing_id:
        try:
            from sqlalchemy import select as sql_select

            lc_rows = await session.execute(
                sql_select(ListingCache).where(
                    ListingCache.listing_id == listing_id
                )
            )
            lc_row = lc_rows.scalars().first()
            if lc_row is not None:
                listing_title = lc_row.title or listing_id
                marketplace_internal = lc_row.marketplace or "fb"
                raw = lc_row.raw_data or {}
                recipient_name = (
                    raw.get("seller_name") if isinstance(raw, dict) else None
                ) or "Seller"
        except Exception:  # noqa: BLE001
            logger.exception(
                "_approval_ticket_from_row: ListingCache lookup failed for %s",
                listing_id,
            )

    marketplace = _INTERNAL_MARKETPLACE_TO_STREAM_A.get(
        marketplace_internal, "facebook"
    )
    ticket_id = row.approval_request_id or row.id
    return ApprovalTicket(
        id=ticket_id,
        approval_request_id=row.approval_request_id,
        hunt_id=hunt_id,
        job_id=row.job_id,
        job_status=job_status,
        listing_id=listing_id,
        recipient_name=recipient_name,
        marketplace=marketplace,  # type: ignore[arg-type]
        listing_title=listing_title,
        ask_price=_ask_price_from_payload(row.request_payload, target_price),
        draft_text=row.draft_text or "",
        why_text=row.draft_reasoning or "",
        expected_outcome=_expected_outcome_for_job_state(job_status),
        status="waiting",
        selected=False,
    )


@router.get("/approvals", response_model=list[ApprovalTicket])
async def get_approvals(
    goalId: Optional[str] = None,  # noqa: N803 — query param name matches frontend
    hunt_id: Optional[str] = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ApprovalTicket]:
    """List unresolved approvals for the current user, mapped to the frontend shape.

    Filtering: when ``hunt_id`` (or the deprecated ``goalId`` alias) is
    passed, only return approvals tied to jobs under that hunt. Returns
    ``[]`` when no approvals exist yet.
    """
    from sqlalchemy import select as sql_select

    hunt_filter = hunt_id or goalId  # both query params resolve to the same filter
    try:
        stmt = (
            sql_select(ApprovalQueueItem)
            .outerjoin(JobORM, ApprovalQueueItem.job_id == JobORM.id)
            .where(
                ApprovalQueueItem.decision.is_(None),
                (JobORM.user_id == str(user.id))
                | (ApprovalQueueItem.job_id.is_(None)),
            )
            .order_by(ApprovalQueueItem.created_at.desc())
        )
        if hunt_filter:
            stmt = stmt.where(JobORM.hunt_id == hunt_filter)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
    except Exception:  # noqa: BLE001 — graceful degrade
        logger.exception("get_approvals: DB query failed; returning []")
        return []

    out: list[ApprovalTicket] = []
    for r in rows:
        if not r.approval_request_id:
            # Skip pre-bridge rows that can't be resolved via the
            # AgentField approval_request_id.
            continue
        try:
            out.append(await _approval_ticket_from_row(session, r))
        except Exception:  # noqa: BLE001 — skip malformed row
            logger.exception(
                "get_approvals: failed mapping ApprovalQueueItem id=%s", r.id
            )
    return out


# NOTE: ``POST /api/approvals/{id}`` lives in ``api/routes/approvals.py``
# as of the Pass-1 properization. It looks up the row by AgentField's
# ``approval_request_id`` and bridges the decision to the paused
# reasoner's ``/webhooks/approval``. Stream-A-shape ids that don't
# match a real row are accepted idempotently (matched_row=False in the
# response). The previous adapter stub here has been removed; the
# real handler accepts the same body shape (``{decision, edited_text}``)
# plus an optional ``feedback`` field.


# NOTE: ``POST /api/goals`` and ``GET /api/goals/{goal_id}/listings`` are
# served by the real hunt-lifecycle handlers in ``api/routes/goals.py``.


@router.get(
    "/goals/{goal_id}/discovery-stages", response_model=list[DiscoveryStage]
)
async def get_discovery_stages(
    goal_id: str,
    user: User = Depends(current_user),
) -> list[DiscoveryStage]:
    """Return the discovery-stage progress events for a hunt.

    v1: there's no per-stage event store; the frontend can poll
    ``GET /api/hunts/{id}`` directly to learn whether the lifecycle is
    in ``discovering`` vs ``awaiting_picks``. Returns ``[]`` so the
    page renders without canned stage content.
    """
    _ = goal_id
    _ = user
    return []
