"""Market REST endpoints (DSD section 6 through 8)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.market.schemas import (
    AttributeVocabCreate,
    AttributeVocabResponse,
    AttributeVocabUpdate,
    ContactIntelligenceResponse,
    ContactProductTagResponse,
    ContactsRankedResponse,
    DealCreateRequest,
    DealResponse,
    DealUpdateRequest,
    MarketArchiveBatchRequest,
    MarketArchiveBatchResult,
    MarketMessageBatchIngest,
    MarketMessageBatchResult,
    MarketMessageIngest,
    MarketMessageResponse,
    MarketReviewItem,
    MarketSearchParams,
    MarketSearchResponse,
    OutreachBatchRequest,
    OutreachSendResponse,
    ProductCreateRequest,
    ProductResponse,
    ProductUpdateRequest,
    ProductWithAliasesResponse,
    ResolveRequest,
    ReviewQueueResponse,
    ReviewStats,
    SavedSearchCreateRequest,
    SavedSearchResponse,
    SearchEventResponse,
)
from app.modules.market.search import MarketSearchService
from app.modules.market.service import (
    MarketIngestionService,
    MarketOutreachService,
    MarketReviewService,
)
from app.schemas.common import Page

router = APIRouter(prefix="/market", tags=["market"])


# --------------------------------------------------------------------------- #
# Ingestion (DSD §2, §3.1)
# --------------------------------------------------------------------------- #


@router.post(
    "/messages",
    response_model=MarketMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_message(
    payload: MarketMessageIngest,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> MarketMessageResponse:
    """Ingest a raw market message from the WhatsApp reader."""
    service = MarketIngestionService(session)
    msg = await service.ingest(
        source_type=payload.source_type,
        source_id=payload.source_id,
        sender_raw=payload.sender_raw,
        raw_text=payload.raw_text,
        captured_at=payload.captured_at,
        dedup_hash=payload.dedup_hash,
        group_name=payload.group_name,
        sender_name=payload.sender_name,
        msg_type=payload.msg_type,
        precomputed=payload.precomputed.model_dump() if payload.precomputed else None,
    )

    # Resolve contact name via explicit async query — lazy loading fails
    # in async sessions regardless of commit timing (MissingGreenlet).
    contact_name: str | None = None
    if msg.contact_id:
        from app.modules.contacts.models import Contact

        contact = await session.get(Contact, msg.contact_id)
        contact_name = contact.name if contact else None

    await session.commit()

    # Dispatch LLM fallback if no keyword products were resolved.
    from app.modules.market.repository import MarketMessageProductRepository

    mmp_repo = MarketMessageProductRepository(session)
    resolutions = await mmp_repo.list_for_message(msg.id)

    if not resolutions or msg.side == "UNKNOWN":
        from app.modules.market.tasks import classify_message_task

        classify_message_task.delay(str(msg.id))

    return await _to_message_response(msg, resolutions, contact_name=contact_name)


@router.post(
    "/messages/batch",
    response_model=list[MarketMessageBatchResult],
    status_code=status.HTTP_201_CREATED,
)
async def ingest_message_batch(
    payload: MarketMessageBatchIngest,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> list[MarketMessageBatchResult]:
    """Batch-ingest up to 50 market messages from the WhatsApp listener.

    Idempotent: duplicate ``dedup_hash`` items report ``status='duplicate'``
    with the existing ``message_id``. Errors are caught per-item so one bad
    payload never fails the whole batch.
    """
    from app.modules.market.repository import MarketMessageProductRepository

    service = MarketIngestionService(session)
    mmp_repo = MarketMessageProductRepository(session)
    results: list[MarketMessageBatchResult] = []
    llm_fallback_ids: list[str] = []

    hashes = [item.dedup_hash for item in payload.items]
    pre_existing = await service._mm.get_existing_hashes(hashes)
    seen_this_batch: dict[str, uuid.UUID] = {}

    for item in payload.items:
        h = item.dedup_hash
        try:
            if h in seen_this_batch:
                results.append(
                    MarketMessageBatchResult(
                        dedup_hash=h,
                        status="duplicate",
                        message_id=seen_this_batch[h],
                    )
                )
                continue

            if h in pre_existing:
                existing = await service._mm.get_by_dedup_hash(h)
                assert existing is not None  # guaranteed: h in pre_existing
                results.append(
                    MarketMessageBatchResult(
                        dedup_hash=h,
                        status="duplicate",
                        message_id=existing.id,
                    )
                )
                seen_this_batch[h] = existing.id
                continue

            msg = await service.ingest(
                source_type=item.source_type,
                source_id=item.source_id,
                sender_raw=item.sender_raw,
                raw_text=item.raw_text,
                captured_at=item.captured_at,
                dedup_hash=item.dedup_hash,
                group_name=item.group_name,
                sender_name=item.sender_name,
                msg_type=item.msg_type,
                precomputed=item.precomputed.model_dump() if item.precomputed else None,
            )
            seen_this_batch[h] = msg.id

            # Defer LLM fallback — must commit before dispatching (Msg-C4).
            resolutions = await mmp_repo.list_for_message(msg.id)
            if not resolutions or msg.side == "UNKNOWN":
                llm_fallback_ids.append(str(msg.id))

            results.append(
                MarketMessageBatchResult(
                    dedup_hash=h,
                    status="created",
                    message_id=msg.id,
                )
            )
        except Exception as exc:
            results.append(
                MarketMessageBatchResult(
                    dedup_hash=h,
                    status="error",
                    detail=str(exc),
                )
            )

    await session.commit()

    # Msg-C4: dispatch tasks AFTER commit so the worker sees durable rows.
    if llm_fallback_ids:
        from app.modules.market.tasks import classify_message_task

        for mid in llm_fallback_ids:
            classify_message_task.delay(mid)

    return results


# --------------------------------------------------------------------------- #
# Archive (P3 — raw message archive, Decision #1 + #4)
# --------------------------------------------------------------------------- #


@router.post(
    "/archive/batch",
    response_model=MarketArchiveBatchResult,
    status_code=status.HTTP_201_CREATED,
)
async def archive_batch(
    payload: MarketArchiveBatchRequest,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> MarketArchiveBatchResult:
    """Ingest raw archived messages from the listener.

    Insert-only — ``ON CONFLICT (source_msg_id) DO NOTHING``.
    Deliberately dumb and fast: no transformation, no normalization.
    """
    import json

    from sqlalchemy import text

    received = len(payload.items)
    inserted = 0
    duplicates = 0

    for item in payload.items:
        tags_raw = item.tags if item.tags is not None else []
        result = await session.execute(
            text(
                "INSERT INTO market_archive "
                "(group_name, sender_name, sender_number, message_timestamp, "
                " message_content, msg_type, tags, source_msg_id, status) "
                "VALUES (:group_name, :sender_name, :sender_number, :message_timestamp, "
                " :message_content, :msg_type, CAST(:tags AS jsonb), :source_msg_id, :status) "
                "ON CONFLICT (source_msg_id) DO NOTHING"
            ),
            {
                "group_name": item.group_name,
                "sender_name": item.sender_name,
                "sender_number": item.sender_number,
                "message_timestamp": item.message_timestamp,
                "message_content": item.message_content,
                "msg_type": item.msg_type,
                "tags": json.dumps(tags_raw),
                "source_msg_id": item.source_msg_id,
                "status": item.status,
            },
        )
        if result.rowcount and result.rowcount > 0:  # type: ignore[attr-defined]
            inserted += 1
        else:
            duplicates += 1

    await session.commit()

    return MarketArchiveBatchResult(
        received=received,
        inserted=inserted,
        duplicates=duplicates,
    )


@router.get("/messages", response_model=Page[MarketMessageResponse])
async def list_messages(
    side: str | None = Query(None),
    status: str | None = Query(None),
    review_status: str | None = Query(None),
    q: str | None = Query(None, description="Search in normalized text"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> Page[MarketMessageResponse]:
    from app.modules.market.repository import (
        MarketMessageProductRepository,
        MarketMessageRepository,
    )

    mm_repo = MarketMessageRepository(session)
    mmp_repo = MarketMessageProductRepository(session)

    offset = (page - 1) * page_size
    items, total = await mm_repo.list_by_side(
        side=side, status=status, review_status=review_status,
        q=q, limit=page_size, offset=offset,
    )

    msg_ids = [m.id for m in items]
    all_res = await mmp_repo.list_for_messages(msg_ids)
    res_map: dict[uuid.UUID, list] = {}
    all_pids: set[uuid.UUID] = set()
    for r in all_res:
        res_map.setdefault(r.market_message_id, []).append(r)
        all_pids.add(r.product_id)

    # Batch-resolve product names.
    prod_names: dict[uuid.UUID, str] = {}
    if all_pids:
        from app.modules.market.models import Product

        p_result = await session.execute(
            sa.select(Product.id, Product.canonical_name).where(
                Product.id.in_(list(all_pids))
            )
        )
        for pid, pname in p_result:
            prod_names[pid] = pname

    # Contact is eagerly loaded via selectinload in list_by_side — cached
    # identity-map hit, no new query. Access is safe in async sessions.
    contact_names: dict[uuid.UUID, str | None] = {}
    for m in items:
        if m.contact_id and m.contact is not None:
            contact_names[m.id] = m.contact.name

    response_items = []
    for m in items:
        response_items.append(
            await _to_message_response(
                m, res_map.get(m.id, []), contact_name=contact_names.get(m.id),
                product_names=prod_names,
            )
        )
    return Page[MarketMessageResponse](
        items=response_items,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/messages/{message_id}", response_model=MarketMessageResponse)
async def get_message(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> MarketMessageResponse:
    from app.modules.market.repository import (
        MarketMessageProductRepository,
        MarketMessageRepository,
    )

    mm_repo = MarketMessageRepository(session)
    msg = await mm_repo.get_or_404(message_id)

    mmp_repo = MarketMessageProductRepository(session)
    resolutions = await mmp_repo.list_for_message(message_id)

    # Resolve product names.
    prod_names: dict[uuid.UUID, str] = {}
    if resolutions:
        from app.modules.market.models import Product

        pids = {r.product_id for r in resolutions}
        p_result = await session.execute(
            sa.select(Product.id, Product.canonical_name).where(
                Product.id.in_(list(pids))
            )
        )
        for pid, pname in p_result:
            prod_names[pid] = pname

    # Resolve contact name via explicit async query — lazy loading fails
    # in async sessions regardless of commit timing (MissingGreenlet).
    contact_name: str | None = None
    if msg.contact_id:
        from app.modules.contacts.models import Contact

        contact = await session.get(Contact, msg.contact_id)
        contact_name = contact.name if contact else None

    return await _to_message_response(msg, resolutions, contact_name=contact_name, product_names=prod_names)


@router.post("/messages/{message_id}/correct", response_model=MarketMessageResponse)
async def correct_message(
    message_id: uuid.UUID,
    payload: ResolveRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> MarketMessageResponse:
    """Correct any market message retroactively — no PENDING restriction.

    Effects (in one transaction): update side → upsert resolutions →
    set REVIEWED → write teach entries (source='human') →
    apply deferred contact tags → audit.
    """
    service = MarketReviewService(session)
    try:
        msg = await service.correct(
            message_id, payload, actor_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()

    from app.modules.market.repository import MarketMessageProductRepository

    mmp_repo = MarketMessageProductRepository(session)
    resolutions = await mmp_repo.list_for_message(msg.id)

    # Resolve product names.
    prod_names: dict[uuid.UUID, str] = {}
    if resolutions:
        from app.modules.market.models import Product

        pids = {r.product_id for r in resolutions}
        p_result = await session.execute(
            sa.select(Product.id, Product.canonical_name).where(
                Product.id.in_(list(pids))
            )
        )
        for pid, pname in p_result:
            prod_names[pid] = pname

    # Fetch contact name via explicit query.
    contact_name: str | None = None
    if msg.contact_id:
        from app.modules.contacts.models import Contact

        result = await session.execute(
            sa.select(Contact.name).where(Contact.id == msg.contact_id)
        )
        row = result.scalar_one_or_none()
        contact_name = row if row else None

    return _to_message_response_with_name(msg, resolutions, contact_name, product_names=prod_names)


# --------------------------------------------------------------------------- #
# Search (DSD §6)
# --------------------------------------------------------------------------- #


@router.get("/search", response_model=MarketSearchResponse)
async def search_market(
    params: MarketSearchParams = Depends(),
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> MarketSearchResponse:
    """Deterministic market search — no AI in query path (R6.1)."""
    service = MarketSearchService(session)
    result = await service.search(params, user_id=current_user.id)
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
# Saved searches (DSD §7.1)
# --------------------------------------------------------------------------- #


@router.post("/saved-searches", response_model=SavedSearchResponse, status_code=201)
async def save_search(
    payload: SavedSearchCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> SavedSearchResponse:
    service = MarketSearchService(session)
    ss = await service.save_search(payload, user_id=current_user.id)
    await session.commit()
    return SavedSearchResponse.model_validate(ss)


@router.get("/saved-searches", response_model=Page[SavedSearchResponse])
async def list_saved_searches(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> Page[SavedSearchResponse]:
    service = MarketSearchService(session)
    items, total = await service.list_saved_searches(
        current_user.id, page=page, page_size=page_size
    )
    return Page[SavedSearchResponse](
        items=[SavedSearchResponse.model_validate(i) for i in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.delete("/saved-searches/{search_id}", status_code=204)
async def delete_saved_search(
    search_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> None:
    service = MarketSearchService(session)
    ok = await service.delete_saved_search(search_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    await session.commit()


# --------------------------------------------------------------------------- #
# Search events (DSD §7.2)
# --------------------------------------------------------------------------- #


@router.get("/search-events", response_model=Page[SearchEventResponse])
async def list_search_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> Page[SearchEventResponse]:
    service = MarketSearchService(session)
    items, total = await service.list_search_events(
        current_user.id, page=page, page_size=page_size
    )
    return Page[SearchEventResponse](
        items=[SearchEventResponse.model_validate(i) for i in items],
        page=page,
        page_size=page_size,
        total=total,
    )


# --------------------------------------------------------------------------- #
# Products (DSD §5)
# --------------------------------------------------------------------------- #


@router.get("/products", response_model=Page[ProductResponse])
async def list_products(
    brand: str | None = Query(None),
    family: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> Page[ProductResponse]:
    service = MarketOutreachService(session)
    items, total = await service.list_products(
        brand=brand, family=family, page=page, page_size=page_size
    )
    return Page[ProductResponse](
        items=[ProductResponse.model_validate(i) for i in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    payload: ProductCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> ProductResponse:
    service = MarketOutreachService(session)
    prod = await service.create_product(payload)
    await session.commit()
    return ProductResponse.model_validate(prod)


@router.get("/products/{product_id}", response_model=ProductWithAliasesResponse)
async def get_product(
    product_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> ProductWithAliasesResponse:
    service = MarketOutreachService(session)
    prod = await service.get_product(product_id)
    if prod is None:
        raise HTTPException(status_code=404, detail="not_found")
    return ProductWithAliasesResponse.model_validate(prod)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> ProductResponse:
    service = MarketOutreachService(session)
    prod = await service.update_product(product_id, payload)
    if prod is None:
        raise HTTPException(status_code=404, detail="not_found")
    await session.commit()
    return ProductResponse.model_validate(prod)


# --------------------------------------------------------------------------- #
# Contact product tags (DSD §3.3)
# --------------------------------------------------------------------------- #


@router.get(
    "/contacts/{contact_id}/product-tags",
    response_model=list[ContactProductTagResponse],
)
async def list_contact_product_tags(
    contact_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> list[ContactProductTagResponse]:
    service = MarketOutreachService(session)
    tags = await service.get_contact_product_tags(contact_id)
    return [ContactProductTagResponse(**t) for t in tags]


# --------------------------------------------------------------------------- #
# Outreach (DSD §8)
# --------------------------------------------------------------------------- #


@router.post(
    "/outreach",
    response_model=list[OutreachSendResponse],
    status_code=status.HTTP_201_CREATED,
)
async def send_outreach(
    payload: OutreachBatchRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> list[OutreachSendResponse]:
    """Send per-contact templated outreach. Auto-creates deals in 'contacted' state."""
    service = MarketOutreachService(session)
    results = await service.send_outreach(payload, sent_by=current_user.id)
    await session.commit()
    return results


# --------------------------------------------------------------------------- #
# Deals (DSD §3.5, §7.3)
# --------------------------------------------------------------------------- #


@router.post("/deals", response_model=DealResponse, status_code=201)
async def create_deal(
    payload: DealCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> DealResponse:
    service = MarketOutreachService(session)
    deal = await service.create_deal(payload, created_by=current_user.id)
    await session.commit()
    return DealResponse.model_validate(deal)


@router.get("/deals", response_model=Page[DealResponse])
async def list_deals(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> Page[DealResponse]:
    service = MarketOutreachService(session)
    items, total = await service.list_deals(status=status, page=page, page_size=page_size)
    return Page[DealResponse](
        items=[DealResponse.model_validate(i) for i in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/deals/{deal_id}", response_model=DealResponse)
async def get_deal(
    deal_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> DealResponse:
    service = MarketOutreachService(session)
    deal = await service.get_deal(deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="not_found")
    return DealResponse.model_validate(deal)


@router.patch("/deals/{deal_id}", response_model=DealResponse)
async def update_deal(
    deal_id: uuid.UUID,
    payload: DealUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> DealResponse:
    service = MarketOutreachService(session)
    deal = await service.update_deal(deal_id, payload)
    if deal is None:
        raise HTTPException(status_code=404, detail="not_found")
    await session.commit()
    return DealResponse.model_validate(deal)


# --------------------------------------------------------------------------- #
# Training export (DSD §7.4)
# --------------------------------------------------------------------------- #


@router.get("/export/training")
async def export_training(
    since: datetime | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> list[dict]:
    """Export training records: search_event → outreach → deal chains."""
    service = MarketOutreachService(session)
    return await service.export_training(since=since)


# --------------------------------------------------------------------------- #
# Review queue (Phase 5)
# --------------------------------------------------------------------------- #


@router.get("/review", response_model=ReviewQueueResponse)
async def list_review_queue(
    page_size: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> ReviewQueueResponse:
    """Keyset-paginated queue of PENDING items ordered by urgency.

    Non-expired items first, ``expires_at ASC`` (soonest-to-die deal on top).
    Cursor is base64-encoded ``expires_at|id`` of the last item.
    """
    service = MarketReviewService(session)
    items, next_cursor = await service.list_pending(cursor=cursor, limit=page_size)
    return ReviewQueueResponse(
        items=[MarketReviewItem(**item) for item in items],
        next_cursor=next_cursor,
    )


@router.post("/review/{message_id}/resolve", response_model=MarketMessageResponse)
async def resolve_review_item(
    message_id: uuid.UUID,
    payload: ResolveRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> MarketMessageResponse:
    """Resolve a PENDING message with corrections.

    Effects (in one transaction): update side → update/insert resolutions →
    set REVIEWED → write teach entries → apply deferred contact tags → audit.
    """
    service = MarketReviewService(session)
    try:
        msg = await service.resolve(
            message_id, payload, actor_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()

    from app.modules.market.repository import MarketMessageProductRepository

    mmp_repo = MarketMessageProductRepository(session)
    resolutions = await mmp_repo.list_for_message(msg.id)

    # Resolve product names.
    prod_names: dict[uuid.UUID, str] = {}
    if resolutions:
        from app.modules.market.models import Product

        pids = {r.product_id for r in resolutions}
        p_result = await session.execute(
            sa.select(Product.id, Product.canonical_name).where(
                Product.id.in_(list(pids))
            )
        )
        for pid, pname in p_result:
            prod_names[pid] = pname

    # Fetch contact name via explicit query to avoid lazy-loading msg.contact
    # across a session-commit boundary (MissingGreenlet guard).
    contact_name: str | None = None
    if msg.contact_id:
        from app.modules.contacts.models import Contact

        result = await session.execute(
            sa.select(Contact.name).where(Contact.id == msg.contact_id)
        )
        row = result.scalar_one_or_none()
        contact_name = row if row else None

    return _to_message_response_with_name(msg, resolutions, contact_name, product_names=prod_names)


@router.post("/review/{message_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_review_item(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> None:
    """Dismiss a PENDING message. No contact writes. Audited."""
    service = MarketReviewService(session)
    try:
        await service.dismiss(message_id, actor_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()


@router.get("/review/stats", response_model=ReviewStats)
async def review_queue_stats(
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> ReviewStats:
    """Queue depth, 7-day inflow/outflow, median review time, capacity estimate."""
    service = MarketReviewService(session)
    data = await service.get_stats()
    return ReviewStats(**data)


# --------------------------------------------------------------------------- #
# Attribute vocabulary (Phase 7)
# --------------------------------------------------------------------------- #


@router.get("/vocab", response_model=list[AttributeVocabResponse])
async def list_vocab(
    category: str | None = Query(None),
    kind: str | None = Query(None),
    active_only: bool = Query(True),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> list[AttributeVocabResponse]:
    """List attribute vocabulary, optionally filtered by category and kind."""
    from app.modules.market.repository import AttributeVocabRepository

    repo = AttributeVocabRepository(session)
    if category:
        items = await repo.list_by_category(category, kind=kind, active_only=active_only)
    else:
        from app.modules.market.models import AttributeVocab

        stmt = sa.select(AttributeVocab)
        if kind is not None:
            stmt = stmt.where(AttributeVocab.kind == kind)
        if active_only:
            stmt = stmt.where(AttributeVocab.is_active == True)  # noqa: E712
        stmt = stmt.order_by(AttributeVocab.category, AttributeVocab.tag)
        result = await session.execute(stmt)
        items = list(result.scalars().all())

    return [AttributeVocabResponse.model_validate(i) for i in items]


@router.post(
    "/vocab",
    response_model=AttributeVocabResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_vocab_entry(
    payload: AttributeVocabCreate,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> AttributeVocabResponse:
    """Create a new attribute vocabulary entry. Admin-only."""
    from app.modules.market.repository import AttributeVocabRepository

    if payload.kind not in ("closed", "open"):
        raise HTTPException(
            status_code=422,
            detail="kind must be 'closed' or 'open'",
        )

    repo = AttributeVocabRepository(session)

    existing = await repo.get_by_tag(payload.category, payload.tag)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate entry: ({payload.category}, {payload.tag}) already exists",
        )

    entry = await repo.create(payload.model_dump())
    await session.commit()
    return AttributeVocabResponse.model_validate(entry)


@router.patch(
    "/vocab/{vocab_id}",
    response_model=AttributeVocabResponse,
)
async def update_vocab_entry(
    vocab_id: uuid.UUID,
    payload: AttributeVocabUpdate,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> AttributeVocabResponse:
    """Update an attribute vocabulary entry. Admin-only."""
    from app.modules.market.repository import AttributeVocabRepository

    repo = AttributeVocabRepository(session)
    entry = await repo.update(vocab_id, payload.model_dump(exclude_unset=True))
    if entry is None:
        raise HTTPException(status_code=404, detail="not_found")
    await session.commit()
    return AttributeVocabResponse.model_validate(entry)


@router.delete("/vocab/{vocab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vocab_entry(
    vocab_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> None:
    """Delete an attribute vocabulary entry. Admin-only."""
    from app.modules.market.repository import AttributeVocabRepository

    repo = AttributeVocabRepository(session)
    ok = await repo.delete(vocab_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    await session.commit()


@router.post(
    "/vocab/seed",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def reseed_vocab(
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> dict:
    """Idempotent re-seed of attribute vocabulary from migration seed data.

    Upserts all entries; existing (category, tag) pairs are updated in-place.
    Admin-only.
    """
    from app.modules.market.repository import AttributeVocabRepository

    repo = AttributeVocabRepository(session)
    upserted = 0

    # Re-import seed data from shared module.
    from app.modules.market.vocab_seed import ALL_SEED_ENTRIES

    for cat, kind, tag, canonical, aliases in ALL_SEED_ENTRIES:
        await repo.upsert_seed(cat, kind, tag, canonical, aliases)
        upserted += 1

    await session.commit()
    return {"upserted": upserted}


# --------------------------------------------------------------------------- #
# Contact intelligence (Phase 12)
# --------------------------------------------------------------------------- #


@router.get(
    "/contacts/{contact_id}/intelligence",
    response_model=ContactIntelligenceResponse,
)
async def get_contact_intelligence(
    contact_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> ContactIntelligenceResponse:
    from app.modules.market.intelligence import ContactIntelligenceService
    from app.modules.market.schemas import (
        AttributePreferenceItem,
        AttributePreferences,
        ContactIntelligenceResponse,
        PriceRangeOut,
        ProductInterestOut,
    )

    service = ContactIntelligenceService(session)
    result = await service.get_intelligence(contact_id)
    return ContactIntelligenceResponse(
        contact_id=result.contact_id,
        contact_name=result.contact_name,
        total_messages=result.total_messages,
        buy_messages=result.buy_messages,
        sell_messages=result.sell_messages,
        active_since=result.active_since,
        last_active=result.last_active,
        products=[
            ProductInterestOut(
                product_id=p.product_id,
                product_name=p.product_name,
                brand=p.brand,
                family=p.family,
                buy_count=p.buy_count,
                sell_count=p.sell_count,
                observation_count=p.observation_count,
                first_seen=p.first_seen,
                last_seen=p.last_seen,
            )
            for p in result.products
        ],
        attribute_preferences=AttributePreferences(
            storage=[AttributePreferenceItem(value=v, count=c) for v, c in result.attribute_preferences.storage],
            ram=[AttributePreferenceItem(value=v, count=c) for v, c in result.attribute_preferences.ram],
            color=[AttributePreferenceItem(value=v, count=c) for v, c in result.attribute_preferences.color],
            region=[AttributePreferenceItem(value=v, count=c) for v, c in result.attribute_preferences.region],
            condition=[AttributePreferenceItem(value=v, count=c) for v, c in result.attribute_preferences.condition],
        ),
        price_range=PriceRangeOut(
            min_unit_price=result.price_range.min_unit_price,
            max_unit_price=result.price_range.max_unit_price,
            currency=result.price_range.currency,
        ),
    )


@router.get(
    "/contacts/ranked",
    response_model=list[ContactsRankedResponse],
)
async def get_contacts_ranked(
    side: str | None = Query(None),
    product_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> list[ContactsRankedResponse]:
    from app.modules.market.intelligence import ContactIntelligenceService
    from app.modules.market.schemas import ContactsRankedResponse

    service = ContactIntelligenceService(session)
    rows = await service.get_contacts_ranked(side=side, product_id=product_id, limit=limit)
    return [ContactsRankedResponse(**r) for r in rows]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _to_message_response(
    msg,
    resolutions: list,
    session: AsyncSession | None = None,
    contact_name: str | None = None,
    product_names: dict[uuid.UUID, str] | None = None,
) -> MarketMessageResponse:
    # Prefer caller-supplied name; fall back to an explicit async load.
    # Avoid lazy-loading msg.contact — it always fails with MissingGreenlet
    # in async sessions.
    if contact_name is None and msg.contact_id is not None:
        if session is not None:
            from app.modules.contacts.models import Contact

            contact = await session.get(Contact, msg.contact_id)
            contact_name = contact.name if contact else None
    return _to_message_response_with_name(
        msg, resolutions, contact_name, product_names=product_names,
    )


def _to_message_response_with_name(
    msg,
    resolutions: list,
    contact_name: str | None,
    product_names: dict[uuid.UUID, str] | None = None,
) -> MarketMessageResponse:
    from app.modules.market.schemas import MarketMessageProductOut

    pnames = product_names or {}
    return MarketMessageResponse(
        id=msg.id,
        source_type=msg.source_type,
        source_id=msg.source_id,
        sender_raw=msg.sender_raw,
        contact_id=msg.contact_id,
        contact_name=contact_name,
        side=msg.side,
        raw_text=msg.raw_text,
        normalized_text=msg.normalized_text,
        captured_at=msg.captured_at,
        expires_at=msg.expires_at,
        status=msg.status,
        review_status=msg.review_status if msg.review_status else "AUTO",
        products=[
            MarketMessageProductOut(
                id=r.id,
                product_id=r.product_id,
                product_name=pnames.get(r.product_id, ""),
                qty=r.qty,
                unit_price=r.unit_price,
                currency=r.currency,
                spec=r.spec,
                condition=r.condition,
                grade=r.grade,
                color=r.color,
                attributes=r.attributes,
                confidence=float(r.confidence),
                resolver=r.resolver,
            )
            for r in resolutions
        ],
        seen_count=msg.seen_count or 1,
        source_groups=msg.source_groups or [],
        created_at=msg.created_at,
    )
