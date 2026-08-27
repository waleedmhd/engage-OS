"""Market module repositories (DSD §3, §6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.orm import selectinload

from app.db.repository import BaseRepository
from app.modules.market.constants import MarketSide, MessageStatus, ReviewStatus
from app.modules.market.models import (
    AttributeVocab,
    ContactProductTag,
    Deal,
    MarketMessage,
    MarketMessageProduct,
    OutreachSend,
    Product,
    ProductAlias,
    SavedSearch,
    SearchEvent,
)

# ==============================================================================
# Market messages
# ==============================================================================


class MarketMessageRepository(BaseRepository[MarketMessage]):
    model = MarketMessage

    async def get_by_dedup_hash(self, dedup_hash: str) -> MarketMessage | None:
        result = await self.session.execute(
            sa.select(MarketMessage).where(MarketMessage.dedup_hash == dedup_hash)
        )
        return result.scalar_one_or_none()

    async def get_existing_hashes(
        self, dedup_hashes: list[str]
    ) -> set[str]:
        """Return the subset of *dedup_hashes* that already exist in the DB."""
        if not dedup_hashes:
            return set()
        result = await self.session.execute(
            sa.select(MarketMessage.dedup_hash).where(
                MarketMessage.dedup_hash.in_(dedup_hashes)
            )
        )
        return {row[0] for row in result}

    async def list_by_side(
        self,
        *,
        side: str | None = None,
        status: str | None = None,
        review_status: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MarketMessage], int]:
        clauses: list[Any] = []
        if side:
            clauses.append(MarketMessage.side == side)
        if status:
            clauses.append(MarketMessage.status == status)
        if review_status:
            clauses.append(MarketMessage.review_status == review_status)
        if q:
            from app.core.config import get_settings

            if get_settings().MARKET_SEARCH_USE_FTS:
                tsquery = sa.func.websearch_to_tsquery("english", q)
                clauses.append(MarketMessage.search_tsv.op("@@")(tsquery))
            else:
                clauses.append(MarketMessage.normalized_text.ilike(f"%{q}%"))

        stmt = sa.select(MarketMessage).options(selectinload(MarketMessage.contact))
        count_stmt = sa.select(sa.func.count()).select_from(MarketMessage)
        if clauses:
            stmt = stmt.where(*clauses)
            count_stmt = count_stmt.where(*clauses)

        stmt = stmt.order_by(MarketMessage.captured_at.desc()).limit(limit).offset(offset)

        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)

    async def search_fts(
        self,
        *,
        q: str | None = None,
        expanded_q: str | None = None,
        side: str | None = None,
        product_ids: list[uuid.UUID] | None = None,
        brand: str | None = None,
        family: str | None = None,
        condition: str | None = None,
        grade: str | None = None,
        limit: int = 50,
        cursor_captured_at: datetime | None = None,
        cursor_id: uuid.UUID | None = None,
    ) -> tuple[list[MarketMessage], int, datetime | None, uuid.UUID | None]:
        """Full-text search with GIN-indexed tsvector + keyset pagination.

        When ``MARKET_SEARCH_USE_FTS`` is True and a query is provided, uses
        ``websearch_to_tsquery`` for user-friendly FTS syntax (quoted phrases,
        ``-exclude``, ``OR``). Falls back to ilike scan when the flag is off.

        When *expanded_q* is set (vocab synonyms OR'd in), it is used for the
        FTS path only — the ilike fallback still uses the original *q*.

        Ranked by ts_rank x recency-decay when FTS is active, otherwise by
        ``captured_at DESC``.

        Keyset pagination via ``(captured_at, id) < (cursor)`` — stable under
        concurrent inserts.
        """
        from app.core.config import get_settings

        use_fts = get_settings().MARKET_SEARCH_USE_FTS and q

        clauses: list[Any] = []
        tsquery = None

        if q and use_fts:
            fts_query = expanded_q or q
            tsquery = sa.func.websearch_to_tsquery("english", fts_query)
            clauses.append(MarketMessage.search_tsv.op("@@")(tsquery))
        elif q:
            clauses.append(MarketMessage.normalized_text.ilike(f"%{q}%"))

        if side:
            clauses.append(MarketMessage.side == side)
        if product_ids:
            clauses.append(
                MarketMessage.id.in_(
                    sa.select(MarketMessageProduct.market_message_id).where(
                        MarketMessageProduct.product_id.in_(product_ids)
                    )
                )
            )
        if brand:
            clauses.append(
                MarketMessage.id.in_(
                    sa.select(MarketMessageProduct.market_message_id)
                    .join(Product, MarketMessageProduct.product_id == Product.id)
                    .where(Product.brand.ilike(f"%{brand}%"))
                )
            )
        if family:
            clauses.append(
                MarketMessage.id.in_(
                    sa.select(MarketMessageProduct.market_message_id)
                    .join(Product, MarketMessageProduct.product_id == Product.id)
                    .where(Product.family.ilike(f"%{family}%"))
                )
            )
        if condition:
            clauses.append(
                MarketMessage.id.in_(
                    sa.select(MarketMessageProduct.market_message_id).where(
                        MarketMessageProduct.condition.ilike(f"%{condition}%")
                    )
                )
            )
        if grade:
            clauses.append(
                MarketMessage.id.in_(
                    sa.select(MarketMessageProduct.market_message_id).where(
                        MarketMessageProduct.grade.ilike(f"%{grade}%")
                    )
                )
            )

        # Keyset pagination: (captured_at, id) < (cursor_captured_at, cursor_id)
        if cursor_captured_at is not None and cursor_id is not None:
            clauses.append(
                sa.or_(
                    MarketMessage.captured_at < cursor_captured_at,
                    sa.and_(
                        MarketMessage.captured_at == cursor_captured_at,
                        MarketMessage.id < cursor_id,
                    ),
                )
            )

        # Ranking: ts_rank x recency-decay when FTS active, else chronological.
        order_by = []
        if tsquery is not None:
            order_by.append(
                sa.func.ts_rank(MarketMessage.search_tsv, tsquery, 32).desc()
            )
        order_by.extend([
            MarketMessage.captured_at.desc(),
            MarketMessage.id.desc(),
        ])

        # Fetch limit+1 so we can detect whether a next page exists without
        # a separate probe query (keyset pagination has no cheap "has more").
        stmt = (
            sa.select(MarketMessage).options(selectinload(MarketMessage.contact))
            .where(*clauses)
            .order_by(*order_by)
            .limit(limit + 1)
        )

        count_stmt = (
            sa.select(sa.func.count()).select_from(MarketMessage).where(*clauses)
        )

        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()

        all_messages = list(rows)
        has_more = len(all_messages) > limit
        messages = all_messages[:limit]

        next_ca: datetime | None = None
        next_id: uuid.UUID | None = None
        if has_more and messages:
            last = messages[-1]
            next_ca = last.captured_at
            next_id = last.id

        return messages, int(total), next_ca, next_id

    async def supersede_repost(
        self, dedup_hash: str, latest_id: uuid.UUID
    ) -> int:
        """Mark older messages with the same dedup_hash as SUPERSEDED (DSD §6.4)."""
        result = await self.session.execute(
            sa.update(MarketMessage)
            .where(
                MarketMessage.dedup_hash == dedup_hash,
                MarketMessage.id != latest_id,
                MarketMessage.status == MessageStatus.ACTIVE.value,
            )
            .values(status=MessageStatus.SUPERSEDED.value)
        )
        await self.session.flush()
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def expire_stale(self, *, buy_minutes: int = 45, sell_hours: int = 48) -> dict:
        """Set ACTIVE messages past their per-side TTL to EXPIRED (DSD §6.3).
        Also closes PENDING messages past expires_at → UNREVIEWED_EXPIRED (Phase 4)."""
        now = datetime.now(tz=UTC)
        buy_cutoff = datetime.fromtimestamp(now.timestamp() - buy_minutes * 60, tz=UTC)
        sell_cutoff = datetime.fromtimestamp(now.timestamp() - sell_hours * 3600, tz=UTC)

        result = await self.session.execute(
            sa.update(MarketMessage)
            .where(
                MarketMessage.status == MessageStatus.ACTIVE.value,
                sa.or_(
                    sa.and_(
                        MarketMessage.side == MarketSide.BUY.value,
                        MarketMessage.captured_at < buy_cutoff,
                    ),
                    sa.and_(
                        MarketMessage.side == MarketSide.SELL.value,
                        MarketMessage.captured_at < sell_cutoff,
                    ),
                    # UNKNOWN side messages expire at the shorter BUY TTL
                    sa.and_(
                        MarketMessage.side == MarketSide.UNKNOWN.value,
                        MarketMessage.captured_at < buy_cutoff,
                    ),
                ),
            )
            .values(status=MessageStatus.EXPIRED.value)
        )
        expired_count: int = result.rowcount or 0  # type: ignore[attr-defined]

        # Second pass: PENDING messages past expires_at → UNREVIEWED_EXPIRED.
        pending_result = await self.session.execute(
            sa.update(MarketMessage)
            .where(
                MarketMessage.review_status == ReviewStatus.PENDING.value,
                MarketMessage.expires_at < now,
            )
            .values(review_status=ReviewStatus.UNREVIEWED_EXPIRED.value)
        )
        unreviewed_count: int = pending_result.rowcount or 0  # type: ignore[attr-defined]

        await self.session.flush()
        return {"expired": expired_count, "unreviewed_expired": unreviewed_count}

    async def list_pending(
        self,
        *,
        cursor_expires_at: datetime | None,
        cursor_id: uuid.UUID | None,
        limit: int = 20,
    ) -> list[MarketMessage]:
        """Keyset-paginated PENDING messages ordered by urgency:
        non-expired first (``expires_at ASC``), then expired (``expires_at ASC``)."""
        from sqlalchemy import case, literal_column

        now = datetime.now(tz=UTC)
        priority = case(
            (MarketMessage.expires_at > now, literal_column("0")),
            else_=literal_column("1"),
        )

        stmt = (
            sa.select(MarketMessage).options(selectinload(MarketMessage.contact))
            .where(MarketMessage.review_status == ReviewStatus.PENDING.value)
            .order_by(priority, MarketMessage.expires_at.asc(), MarketMessage.id.asc())
            .limit(limit)
        )

        if cursor_expires_at is not None and cursor_id is not None:
            cursor_priority: Any = literal_column(
                "0" if cursor_expires_at > now else "1"
            )
            stmt = stmt.where(
                sa.or_(
                    priority > cursor_priority,
                    sa.and_(
                        priority == cursor_priority,
                        MarketMessage.expires_at > cursor_expires_at,
                    ),
                    sa.and_(
                        priority == cursor_priority,
                        MarketMessage.expires_at == cursor_expires_at,
                        MarketMessage.id > cursor_id,
                    ),
                )
            )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_review_stats_raw(self) -> dict:
        """Raw review-queue stats via a single aggregation query."""
        from sqlalchemy import text as sa_text

        sql = sa_text(
            """
            WITH windowed AS (
                SELECT
                    review_status,
                    created_at,
                    updated_at,
                    expires_at,
                    CASE WHEN review_status IN ('REVIEWED', 'DISMISSED')
                         THEN EXTRACT(EPOCH FROM (updated_at - created_at))
                    END AS review_seconds
                FROM market_messages
                WHERE review_status != 'AUTO'
                  AND (
                      review_status = 'PENDING'
                      OR review_status = 'UNREVIEWED_EXPIRED'
                      OR updated_at >= NOW() - INTERVAL '30 days'
                  )
            )
            SELECT
                COALESCE(SUM(CASE WHEN review_status = 'PENDING' THEN 1 ELSE 0 END), 0) AS queue_depth,
                COALESCE(SUM(CASE WHEN review_status = 'PENDING' AND created_at >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END), 0) AS inflow_7d,
                COALESCE(SUM(CASE WHEN review_status IN ('REVIEWED', 'DISMISSED', 'UNREVIEWED_EXPIRED')
                                  AND updated_at >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END), 0) AS outflow_7d,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY review_seconds) AS median_review_seconds
            FROM windowed
            """
        )
        result = await self.session.execute(sql)
        row = result.one()
        return {
            "queue_depth": int(row.queue_depth),
            "inflow_7d": int(row.inflow_7d),
            "outflow_7d": int(row.outflow_7d),
            "median_review_seconds": (
                float(row.median_review_seconds)
                if row.median_review_seconds is not None
                else None
            ),
        }

    def get_sync(self, mid: uuid.UUID) -> MarketMessage | None:
        session: SyncSession = self.session  # type: ignore[assignment]
        return session.get(MarketMessage, mid)

    def expire_stale_sync(
        self, *, buy_minutes: int = 45, sell_hours: int = 48
    ) -> dict:
        """Sync version for Celery beat task. Includes PENDING sweep (Phase 4)."""
        session: SyncSession = self.session  # type: ignore[assignment]
        now = datetime.now(tz=UTC)
        buy_cutoff = datetime.fromtimestamp(now.timestamp() - buy_minutes * 60, tz=UTC)
        sell_cutoff = datetime.fromtimestamp(now.timestamp() - sell_hours * 3600, tz=UTC)

        result = session.execute(
            sa.update(MarketMessage)
            .where(
                MarketMessage.status == MessageStatus.ACTIVE.value,
                sa.or_(
                    sa.and_(
                        MarketMessage.side == MarketSide.BUY.value,
                        MarketMessage.captured_at < buy_cutoff,
                    ),
                    sa.and_(
                        MarketMessage.side == MarketSide.SELL.value,
                        MarketMessage.captured_at < sell_cutoff,
                    ),
                    sa.and_(
                        MarketMessage.side == MarketSide.UNKNOWN.value,
                        MarketMessage.captured_at < buy_cutoff,
                    ),
                ),
            )
            .values(status=MessageStatus.EXPIRED.value)
        )
        expired_count: int = result.rowcount or 0  # type: ignore[attr-defined]

        # Second pass: PENDING messages past expires_at → UNREVIEWED_EXPIRED.
        pending_result = session.execute(
            sa.update(MarketMessage)
            .where(
                MarketMessage.review_status == ReviewStatus.PENDING.value,
                MarketMessage.expires_at < now,
            )
            .values(review_status=ReviewStatus.UNREVIEWED_EXPIRED.value)
        )
        unreviewed_count: int = pending_result.rowcount or 0  # type: ignore[attr-defined]

        session.flush()
        return {"expired": expired_count, "unreviewed_expired": unreviewed_count}


# ==============================================================================
# Products
# ==============================================================================


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def get_by_canonical_name(self, name: str) -> Product | None:
        result = await self.session.execute(
            sa.select(Product).where(
                sa.func.lower(Product.canonical_name) == name.lower()
            )
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        brand: str | None = None,
        family: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[Product], int]:
        clauses: list[Any] = [Product.is_active == True]  # noqa: E712
        if brand:
            clauses.append(Product.brand.ilike(f"%{brand}%"))
        if family:
            clauses.append(Product.family.ilike(f"%{family}%"))

        stmt = sa.select(Product).where(*clauses).order_by(
            Product.brand, Product.family, Product.canonical_name
        ).limit(limit).offset(offset)

        count_stmt = sa.select(sa.func.count()).select_from(Product).where(*clauses)

        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)

    async def list_all_active(self) -> list[Product]:
        result = await self.session.execute(
            sa.select(Product).where(Product.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())


# ==============================================================================
# Product aliases
# ==============================================================================


class ProductAliasRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(self, text: str) -> list[tuple[ProductAlias, Product]]:
        """Find all aliases that appear as substrings in *text* (keyword classifier)."""
        result = await self.session.execute(
            sa.select(ProductAlias, Product)
            .join(Product, ProductAlias.product_id == Product.id)
            .where(Product.is_active == True)  # noqa: E712
            .order_by(sa.func.length(ProductAlias.alias).desc())
        )
        matches: list[tuple[ProductAlias, Product]] = []
        text_lower = text.lower()
        for alias, product in result:
            if alias.alias.lower() in text_lower:
                matches.append((alias, product))
        return matches

    async def get_by_alias(self, alias: str) -> ProductAlias | None:
        result = await self.session.execute(
            sa.select(ProductAlias).where(
                sa.func.lower(ProductAlias.alias) == alias.lower()
            )
        )
        return result.scalar_one_or_none()

    async def upsert_learned(
        self, product_id: uuid.UUID, alias: str
    ) -> ProductAlias:
        """Insert a novel LLM-learned alias. Idempotent (ON CONFLICT DO NOTHING)."""
        stmt = (
            pg_insert(ProductAlias)
            .values(product_id=product_id, alias=alias.lower(), source="llm_learned")
            .on_conflict_do_nothing(
                index_elements=["product_id", "alias"]
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

        result = await self.session.execute(
            sa.select(ProductAlias).where(
                ProductAlias.product_id == product_id,
                sa.func.lower(ProductAlias.alias) == alias.lower(),
            )
        )
        return result.scalar_one()


# ==============================================================================
# Market-message-product resolutions
# ==============================================================================


class MarketMessageProductRepository(BaseRepository[MarketMessageProduct]):
    model = MarketMessageProduct

    async def list_for_message(self, message_id: uuid.UUID) -> list[MarketMessageProduct]:
        result = await self.session.execute(
            sa.select(MarketMessageProduct).where(
                MarketMessageProduct.market_message_id == message_id
            )
        )
        return list(result.scalars().all())

    async def list_for_messages(
        self, message_ids: list[uuid.UUID]
    ) -> list[MarketMessageProduct]:
        result = await self.session.execute(
            sa.select(MarketMessageProduct).where(
                MarketMessageProduct.market_message_id.in_(message_ids)
            )
        )
        return list(result.scalars().all())


# ==============================================================================
# Contact product tags (derived, not manual — DSD §3.3)
# ==============================================================================


class ContactProductTagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def increment_tag(
        self,
        *,
        contact_id: uuid.UUID,
        product_id: uuid.UUID,
        side: str,
        confidence: float | None = None,
    ) -> None:
        """Atomic server-side increment (DB-I8 pattern). Creates the tag on first sight.

        When *confidence* is provided and falls below the auto threshold,
        the increment is skipped entirely (corruption guard — Phase 4).
        """
        if confidence is not None:
            auto_min = await self._read_auto_min()
            if confidence < auto_min:
                return

        now = datetime.now(tz=UTC)
        buy_delta = 1 if side == MarketSide.BUY.value else 0
        sell_delta = 1 if side == MarketSide.SELL.value else 0

        # Try insert first with ON CONFLICT update pattern.
        stmt = (
            pg_insert(ContactProductTag)
            .values(
                contact_id=contact_id,
                product_id=product_id,
                side_buy_count=buy_delta,
                side_sell_count=sell_delta,
                observation_count=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            .on_conflict_do_update(
                index_elements=["contact_id", "product_id"],
                set_={
                    "side_buy_count": ContactProductTag.side_buy_count + buy_delta,
                    "side_sell_count": ContactProductTag.side_sell_count + sell_delta,
                    "observation_count": ContactProductTag.observation_count + 1,
                    "last_seen_at": now,
                },
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def list_for_contact(self, contact_id: uuid.UUID) -> list[dict]:
        result = await self.session.execute(
            sa.select(ContactProductTag, Product)
            .join(Product, ContactProductTag.product_id == Product.id)
            .where(ContactProductTag.contact_id == contact_id)
            .order_by(ContactProductTag.last_seen_at.desc())
        )
        output: list[dict] = []
        for cpt, prod in result:
            output.append({
                "contact_id": cpt.contact_id,
                "product_id": cpt.product_id,
                "product_name": prod.canonical_name,
                "product_brand": prod.brand,
                "side_buy_count": cpt.side_buy_count,
                "side_sell_count": cpt.side_sell_count,
                "observation_count": cpt.observation_count,
                "first_seen_at": cpt.first_seen_at,
                "last_seen_at": cpt.last_seen_at,
            })
        return output

    async def _read_auto_min(self) -> float:
        """Read the auto-min confidence threshold from AppSetting."""
        from sqlalchemy import and_ as sa_and
        from sqlalchemy import select as sa_select

        from app.modules.settings.models import AppSetting

        stmt = sa_select(AppSetting).where(
            sa_and(AppSetting.key == "market.confidence.auto_min", AppSetting.scope == "global")
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None or not isinstance(row.value, dict) or "value" not in row.value:
            return 0.85
        try:
            return float(row.value["value"])
        except (ValueError, TypeError):
            return 0.85

    def increment_tag_sync(
        self,
        *,
        contact_id: uuid.UUID,
        product_id: uuid.UUID,
        side: str,
        confidence: float | None = None,
    ) -> None:
        """Sync version for Celery tasks. Supports corruption guard via *confidence*."""
        if confidence is not None:
            from app.modules.settings.repository import get_numeric_setting_sync

            auto_min = get_numeric_setting_sync(
                self.session,  # type: ignore[arg-type]
                "market.confidence.auto_min",
                default=0.85,
            )
            if confidence < auto_min:
                return

        session: SyncSession = self.session  # type: ignore[assignment]
        now = datetime.now(tz=UTC)
        buy_delta = 1 if side == MarketSide.BUY.value else 0
        sell_delta = 1 if side == MarketSide.SELL.value else 0
        stmt = (
            pg_insert(ContactProductTag)
            .values(
                contact_id=contact_id,
                product_id=product_id,
                side_buy_count=buy_delta,
                side_sell_count=sell_delta,
                observation_count=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            .on_conflict_do_update(
                index_elements=["contact_id", "product_id"],
                set_={
                    "side_buy_count": ContactProductTag.side_buy_count + buy_delta,
                    "side_sell_count": ContactProductTag.side_sell_count + sell_delta,
                    "observation_count": ContactProductTag.observation_count + 1,
                    "last_seen_at": now,
                },
            )
        )
        session.execute(stmt)
        session.flush()


# ==============================================================================
# Saved searches
# ==============================================================================


class SavedSearchRepository(BaseRepository[SavedSearch]):
    model = SavedSearch

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[SavedSearch], int]:
        stmt = (
            sa.select(SavedSearch)
            .where(SavedSearch.user_id == user_id)
            .order_by(SavedSearch.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = (
            sa.select(sa.func.count())
            .select_from(SavedSearch)
            .where(SavedSearch.user_id == user_id)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)


# ==============================================================================
# Search events
# ==============================================================================


class SearchEventRepository(BaseRepository[SearchEvent]):
    model = SearchEvent

    async def list_recent(
        self, user_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[SearchEvent], int]:
        stmt = (
            sa.select(SearchEvent)
            .where(SearchEvent.user_id == user_id)
            .order_by(SearchEvent.executed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = (
            sa.select(sa.func.count())
            .select_from(SearchEvent)
            .where(SearchEvent.user_id == user_id)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)


# ==============================================================================
# Outreach sends
# ==============================================================================


class OutreachSendRepository(BaseRepository[OutreachSend]):
    model = OutreachSend

    async def list_for_search_event(
        self, search_event_id: uuid.UUID
    ) -> list[OutreachSend]:
        result = await self.session.execute(
            sa.select(OutreachSend).where(
                OutreachSend.search_event_id == search_event_id
            )
        )
        return list(result.scalars().all())

    async def list_for_contact(
        self, contact_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[OutreachSend]:
        result = await self.session.execute(
            sa.select(OutreachSend)
            .where(OutreachSend.contact_id == contact_id)
            .order_by(OutreachSend.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


# ==============================================================================
# Deals
# ==============================================================================


class DealRepository(BaseRepository[Deal]):
    model = Deal

    async def list_by_status(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Deal], int]:
        clauses: list[Any] = []
        if status:
            clauses.append(Deal.status == status)

        stmt = sa.select(Deal).order_by(Deal.created_at.desc()).limit(limit).offset(offset)
        count_stmt = sa.select(sa.func.count()).select_from(Deal)
        if clauses:
            stmt = stmt.where(*clauses)
            count_stmt = count_stmt.where(*clauses)

        rows = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(rows), int(total)

    async def get_for_export(
        self,
        *,
        search_event_ids: list[uuid.UUID],
    ) -> list[Deal]:
        result = await self.session.execute(
            sa.select(Deal).where(
                Deal.origin_search_event_id.in_(search_event_ids)
            )
        )
        return list(result.scalars().all())


# ==============================================================================
# Attribute vocabulary (Phase 7)
# ==============================================================================


class AttributeVocabRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_category(
        self,
        category: str,
        kind: str | None = None,
        active_only: bool = True,
    ) -> list[AttributeVocab]:
        clauses: list[Any] = [AttributeVocab.category == category]
        if kind is not None:
            clauses.append(AttributeVocab.kind == kind)
        if active_only:
            clauses.append(AttributeVocab.is_active == True)  # noqa: E712

        result = await self.session.execute(
            sa.select(AttributeVocab)
            .where(*clauses)
            .order_by(AttributeVocab.tag)
        )
        return list(result.scalars().all())

    async def get_by_tag(
        self, category: str, tag: str
    ) -> AttributeVocab | None:
        result = await self.session.execute(
            sa.select(AttributeVocab).where(
                AttributeVocab.category == category,
                AttributeVocab.tag == tag,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> AttributeVocab:
        instance = AttributeVocab(**data)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(
        self, vocab_id: uuid.UUID, data: dict
    ) -> AttributeVocab | None:
        instance = await self.session.get(AttributeVocab, vocab_id)
        if instance is None:
            return None
        for key, value in data.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, vocab_id: uuid.UUID) -> bool:
        instance = await self.session.get(AttributeVocab, vocab_id)
        if instance is None:
            return False
        await self.session.delete(instance)
        await self.session.flush()
        return True

    async def upsert_seed(
        self, category: str, kind: str, tag: str, canonical: str, aliases: list
    ) -> AttributeVocab:
        """Idempotent seed upsert — insert or update existing entry."""
        stmt = (
            pg_insert(AttributeVocab)
            .values(
                category=category,
                kind=kind,
                tag=tag,
                canonical=canonical,
                aliases=aliases,
                is_active=True,
            )
            .on_conflict_do_update(
                index_elements=["category", "tag"],
                set_={
                    "kind": kind,
                    "canonical": canonical,
                    "aliases": aliases,
                    "is_active": True,
                    "updated_at": datetime.now(tz=UTC),
                },
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

        result = await self.session.execute(
            sa.select(AttributeVocab).where(
                AttributeVocab.category == category,
                AttributeVocab.tag == tag,
            )
        )
        return result.scalar_one()
