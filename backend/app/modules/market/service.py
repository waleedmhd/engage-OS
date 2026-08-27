"""Market services - ingestion, classification, search, outreach, deals (DSD sections 4 through 8)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.core.config import get_settings
from app.modules.contacts.repository import ContactRepository
from app.modules.market.constants import (
    BUY_EXPIRY_MINUTES,
    BUY_PATTERNS,
    KEYWORD_CONFIDENCE,
    LLM_CONFIDENCE_FLOOR,
    SELL_EXPIRY_HOURS,
    SELL_PATTERNS,
    AliasSource,
    MarketSide,
    ResolverKind,
    ReviewStatus,
)
from app.modules.market.extractor import extract_attributes, extract_intent
from app.modules.market.models import (
    ContactProductTag,
    Deal,
    MarketMessage,
    MarketMessageProduct,
    Product,
    ProductAlias,
    SearchEvent,
)
from app.modules.market.repository import (
    ContactProductTagRepository,
    DealRepository,
    MarketMessageProductRepository,
    MarketMessageRepository,
    OutreachSendRepository,
    ProductAliasRepository,
    ProductRepository,
)
from app.modules.market.schemas import (
    DealCreateRequest,
    DealUpdateRequest,
    OutreachBatchRequest,
    OutreachSendResponse,
    ProductCreateRequest,
    ProductUpdateRequest,
    TrainingExportRecord,
)


def _normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, strip non-alphanumeric edge chars."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _classify_side(normalized: str) -> str:
    """Classify BUY vs SELL via keyword patterns (DSD §4.1)."""
    for pat in BUY_PATTERNS:
        if pat in normalized:
            return MarketSide.BUY.value
    for pat in SELL_PATTERNS:
        if pat in normalized:
            return MarketSide.SELL.value
    return MarketSide.UNKNOWN.value


def _compute_expiry(side: str, captured_at: datetime) -> datetime:
    if side == MarketSide.BUY.value:
        return captured_at + timedelta(minutes=BUY_EXPIRY_MINUTES)
    return captured_at + timedelta(hours=SELL_EXPIRY_HOURS)


# ==============================================================================
# Ingestion service (write-time — async HTTP path)
# ==============================================================================


class MarketIngestionService:
    """Ingestion pipeline: validate dedup, resolve contact, classify side (keyword),
    resolve products (keyword+alias), dispatch LLM fallback tasks."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._mm = MarketMessageRepository(session)
        self._products = ProductRepository(session)
        self._aliases = ProductAliasRepository(session)
        self._mmp = MarketMessageProductRepository(session)
        self._cpt = ContactProductTagRepository(session)
        self._contacts = ContactRepository(session)

    async def ingest(
        self,
        *,
        source_type: str,
        source_id: str | None,
        sender_raw: str | None,
        raw_text: str,
        captured_at: datetime,
        dedup_hash: str,
        group_name: str | None = None,
        sender_name: str | None = None,
        msg_type: str | None = None,
        precomputed: dict | None = None,
    ) -> MarketMessage:
        # Idempotency check (DSD §11 test priority 1).
        existing = await self._mm.get_by_dedup_hash(dedup_hash)
        if existing is not None:
            return existing

        normalized = _normalize_text(raw_text)
        side = _classify_side(normalized)
        expires_at = _compute_expiry(side, captured_at)

        # Resolve sender to contact.
        contact_id: uuid.UUID | None = None
        if sender_raw:
            contact = await self._contacts.upsert_by_phone(sender_raw)
            contact_id = contact.id

        # P10: fingerprint dedup — resolve product IDs early for fingerprint.
        product_ids_for_fp = await self._resolve_product_ids_for_fingerprint(
            normalized, precomputed
        )
        storage_for_fp = self._extract_storage(precomputed)

        # Try Redis fingerprint gate (degrade gracefully if Redis is down).
        fp_collision_id = await self._check_fingerprint(
            sender_raw=sender_raw or "",
            side=side,
            product_ids=sorted(str(pid) for pid in product_ids_for_fp),
            storage=storage_for_fp,
            source_id=source_id,
            group_name=group_name,
            captured_at=captured_at,
        )
        if fp_collision_id is not None:
            # Fingerprint hit — bump the existing row, don't create a new one.
            bumped = await self._bump_fingerprint_row(
                fp_collision_id,
                source_id=source_id,
                group_name=group_name,
                captured_at=captured_at,
            )
            if bumped is not None:
                return bumped
            # If the bumped row disappeared, fall through and create normally.

        message = await self._mm.create(
            source_type=source_type,
            source_id=source_id,
            sender_raw=sender_raw,
            contact_id=contact_id,
            side=side,
            raw_text=raw_text,
            normalized_text=normalized,
            captured_at=captured_at,
            expires_at=expires_at,
            dedup_hash=dedup_hash,
            group_name=group_name,
            sender_name=sender_name,
            msg_type=msg_type,
        )

        # Decision #2: trust listener precomputed output during transition.
        trusted = (
            get_settings().MARKET_TRUST_LISTENER
            and precomputed is not None
            and precomputed.get("version", "").startswith("listener-")
        )

        if trusted:
            assert precomputed is not None  # guaranteed by trusted check above
            await self._apply_precomputed(message, precomputed)
        else:
            # Phase 8: Python extractor (Pass B+C port) when listener not trusted.
            intent = extract_intent(raw_text)
            attrs = extract_attributes(raw_text)

            message.extracted_attributes = {**intent, **attrs}

            # Override keyword side with extractor side when confident.
            if intent["side"] != "unknown":
                message.side = intent["side"].upper()
                message.expires_at = _compute_expiry(message.side, message.captured_at)

            # Non-target brand → route to PENDING for human review.
            if not attrs.get("passed"):
                message.review_status = ReviewStatus.PENDING.value
                await self._session.flush()
                return message

            # Classify products via keyword+alias (fast path).
            await self._classify_keywords(message)

        # Supersede previous posts with same dedup_hash.
        await self._mm.supersede_repost(dedup_hash, message.id)

        # Three-band confidence routing (Phase 4).
        await self._apply_confidence_routing(message)

        # P10: register fingerprint in Redis after successful insert.
        await self._set_fingerprint_key(
            sender_raw=sender_raw or "",
            side=side,
            product_ids=sorted(str(pid) for pid in product_ids_for_fp),
            storage=storage_for_fp,
            message_id=str(message.id),
        )

        await self._session.flush()
        return message

    async def _read_numeric_setting(self, key: str, default: float) -> float:
        """Read a {"value": number} AppSetting from the async session."""
        from app.modules.settings.models import AppSetting

        stmt = sa.select(AppSetting).where(
            sa.and_(AppSetting.key == key, AppSetting.scope == "global")
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None or not isinstance(row.value, dict) or "value" not in row.value:
            return default
        try:
            return float(row.value["value"])
        except (ValueError, TypeError):
            return default

    # -- P10 fingerprint helpers --------------------------------------------------

    @staticmethod
    def _compute_fingerprint_hash(
        sender_raw: str,
        side: str,
        product_ids: list[str],
        storage: str,
    ) -> str:
        raw = f"{sender_raw}|{side}|{','.join(product_ids)}|{storage}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _resolve_product_ids_for_fingerprint(
        self, normalized: str, precomputed: dict | None
    ) -> set[uuid.UUID]:
        """Resolve product IDs from both keyword matching and precomputed hints."""
        ids: set[uuid.UUID] = set()

        # Keyword path — alias substring matching.
        matches = await self._aliases.resolve(normalized)
        for _alias_row, product in matches:
            ids.add(product.id)

        # Precomputed path — resolve hints via alias lookup.
        if precomputed:
            for pp in precomputed.get("products", []) or []:
                hint: str = (pp.get("hint") or "").strip().lower()
                if not hint:
                    continue
                alias_row = await self._aliases.get_by_alias(hint)
                if alias_row is not None:
                    ids.add(alias_row.product_id)

        return ids

    @staticmethod
    def _extract_storage(precomputed: dict | None) -> str:
        """Extract storage values from precomputed products, deduped and sorted."""
        if not precomputed:
            return ""
        storages: set[str] = set()
        for pp in precomputed.get("products", []) or []:
            s = pp.get("storage")
            if s:
                storages.add(str(s).strip().lower())
        return ",".join(sorted(storages))

    async def _check_fingerprint(
        self,
        *,
        sender_raw: str,
        side: str,
        product_ids: list[str],
        storage: str,
        source_id: str | None,
        group_name: str | None,
        captured_at: datetime,
    ) -> uuid.UUID | None:
        """Try to claim a fingerprint key in Redis.

        Returns the existing message_id if the fingerprint is already claimed,
        or None if this is the first sighting (or Redis is unavailable).
        """
        settings = get_settings()
        window_hours = settings.MARKET_FINGERPRINT_WINDOW_HOURS
        if window_hours <= 0:
            return None

        fp_hash = self._compute_fingerprint_hash(sender_raw, side, product_ids, storage)
        ttl = window_hours * 3600
        key = f"market:fingerprint:{fp_hash}"

        try:
            from app.core.redis import get_async_redis

            redis_client = get_async_redis()
            claimed = await redis_client.set(key, "pending", nx=True, ex=ttl)
            if claimed:
                return None  # First sighting — proceed with new row.

            # Fingerprint already exists — get the existing message_id.
            existing_id_str = await redis_client.get(key)
            if existing_id_str and existing_id_str != "pending":
                try:
                    return uuid.UUID(existing_id_str)
                except ValueError:
                    pass
            return None
        except Exception:
            # Redis unavailable — degrade to no fingerprinting.
            return None

    async def _set_fingerprint_key(
        self,
        *,
        sender_raw: str,
        side: str,
        product_ids: list[str],
        storage: str,
        message_id: str,
    ) -> None:
        """Update the fingerprint Redis key with the actual message_id after insert."""
        settings = get_settings()
        window_hours = settings.MARKET_FINGERPRINT_WINDOW_HOURS
        if window_hours <= 0:
            return

        fp_hash = self._compute_fingerprint_hash(sender_raw, side, product_ids, storage)
        key = f"market:fingerprint:{fp_hash}"

        try:
            from app.core.redis import get_async_redis

            redis_client = get_async_redis()
            await redis_client.set(key, message_id, xx=True, keepttl=True)
        except Exception:
            pass  # Best-effort — Redis is optional for fingerprinting.

    async def _bump_fingerprint_row(
        self,
        message_id: uuid.UUID,
        *,
        source_id: str | None,
        group_name: str | None,
        captured_at: datetime,
    ) -> MarketMessage | None:
        """Bump seen_count and append source_groups entry on a fingerprint hit."""
        existing = await self._mm.get(message_id)
        if existing is None:
            return None

        new_groups: list[dict] = list(existing.source_groups or [])
        new_groups.append({
            "source_id": source_id,
            "group_name": group_name,
            "at": captured_at.isoformat(),
        })
        existing.source_groups = new_groups
        existing.seen_count = (existing.seen_count or 1) + 1
        # Keep earliest captured_at.
        if captured_at < existing.captured_at:
            existing.captured_at = captured_at
        # Refresh TTL per side rules.
        existing.expires_at = _compute_expiry(existing.side, captured_at)
        existing.updated_at = datetime.now(tz=UTC)
        await self._session.flush()
        return existing

    async def _apply_confidence_routing(self, message: MarketMessage) -> None:
        """Route message into AUTO / PENDING / UNRESOLVED band based on
        the minimum per-resolution confidence."""
        resolutions = await self._mmp.list_for_message(message.id)
        if not resolutions:
            return

        min_conf = min(float(r.confidence) for r in resolutions)

        auto_min = await self._read_numeric_setting(
            "market.confidence.auto_min", 0.85
        )
        review_min = await self._read_numeric_setting(
            "market.confidence.review_min", 0.55
        )

        if min_conf >= auto_min:
            message.review_status = ReviewStatus.AUTO.value
        elif min_conf >= review_min:
            message.review_status = ReviewStatus.PENDING.value
        else:
            message.review_status = ReviewStatus.AUTO.value
            for r in resolutions:
                attrs = dict(r.attributes or {})
                attrs["_unresolved"] = True
                r.attributes = attrs

    async def _apply_precomputed(
        self, message: MarketMessage, precomputed: dict
    ) -> None:
        """Apply listener precomputed output verbatim (Decision #2)."""
        pc_side = precomputed.get("side", message.side)
        if pc_side in (MarketSide.BUY.value, MarketSide.SELL.value,
                       MarketSide.MIXED.value, MarketSide.UNKNOWN.value):
            message.side = pc_side
            message.expires_at = _compute_expiry(pc_side, message.captured_at)

        block_attrs: dict = precomputed.get("attributes") or {}

        for pp in precomputed.get("products", []) or []:
            hint: str = (pp.get("hint") or "").strip().lower()
            if not hint:
                continue

            alias_row = await self._aliases.get_by_alias(hint)
            if alias_row is None:
                continue

            product = await self._products.get(alias_row.product_id)
            if product is None:
                continue

            per_field_conf = {"side": KEYWORD_CONFIDENCE, "product": KEYWORD_CONFIDENCE}
            mmp_attrs: dict = {**block_attrs, "_confidence": per_field_conf}
            storage = pp.get("storage")
            if storage:
                mmp_attrs["storage"] = storage

            await self._mmp.create(
                market_message_id=message.id,
                product_id=product.id,
                qty=pp.get("qty"),
                unit_price=pp.get("unit_price"),
                currency=pp.get("currency"),
                spec=pp.get("spec_region"),
                condition=pp.get("condition"),
                grade=pp.get("grade"),
                color=pp.get("color"),
                attributes=mmp_attrs,
                confidence=KEYWORD_CONFIDENCE,
                resolver=ResolverKind.KEYWORD.value,
                side=pc_side,
            )

            if message.contact_id:
                await self._cpt.increment_tag(
                    contact_id=message.contact_id,
                    product_id=product.id,
                    side=pc_side,
                    confidence=KEYWORD_CONFIDENCE,
                )

    async def _classify_keywords(self, message: MarketMessage) -> None:
        """Resolve products via alias substring matching (DSD §4.1)."""
        matches = await self._aliases.resolve(message.normalized_text)
        if not matches:
            return

        per_field_conf = {"side": KEYWORD_CONFIDENCE, "product": KEYWORD_CONFIDENCE}
        seen: set[uuid.UUID] = set()
        for _alias_row, product in matches:
            if product.id in seen:
                continue
            seen.add(product.id)

            await self._mmp.create(
                market_message_id=message.id,
                product_id=product.id,
                confidence=KEYWORD_CONFIDENCE,
                resolver=ResolverKind.KEYWORD.value,
                attributes={"_confidence": per_field_conf},
            )
            # Increment contact product tag (guard applies inside).
            if message.contact_id:
                await self._cpt.increment_tag(
                    contact_id=message.contact_id,
                    product_id=product.id,
                    side=message.side,
                    confidence=KEYWORD_CONFIDENCE,
                )


# ==============================================================================
# Outreach & deal pipeline (DSD §8, §3.5)
# ==============================================================================


class MarketOutreachService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._outreach = OutreachSendRepository(session)
        self._deals = DealRepository(session)

    async def send_outreach(
        self, payload: OutreachBatchRequest, *, sent_by: uuid.UUID
    ) -> list[OutreachSendResponse]:
        """Create outreach_send rows + auto-create deals in 'contacted' state (R8.4)."""
        results: list[OutreachSendResponse] = []
        for s in payload.sends:
            o = await self._outreach.create(
                search_event_id=payload.search_event_id,
                contact_id=s.contact_id,
                market_message_id=s.market_message_id,
                template_id=s.template_id,
                sent_by=sent_by,
            )
            # Auto-create deal in contacted state (DSD §8 R8.4).
            # The contact is the buyer since we're reaching out about their lead.
            await self._deals.create(
                buyer_contact_id=s.contact_id,
                origin_search_event_id=payload.search_event_id,
                created_by=sent_by,
            )

            results.append(
                OutreachSendResponse(
                    id=o.id,
                    search_event_id=o.search_event_id,
                    contact_id=o.contact_id,
                    market_message_id=o.market_message_id,
                    template_id=o.template_id,
                    rendered_body=o.rendered_body,
                    status=o.status,
                    sent_at=o.sent_at,
                    created_at=o.created_at,
                )
            )
        await self._session.flush()
        return results

    # ------------------------------------------------------------------- deals

    async def create_deal(
        self, payload: DealCreateRequest, *, created_by: uuid.UUID
    ) -> Deal:
        return await self._deals.create(
            buyer_contact_id=payload.buyer_contact_id,
            seller_contact_id=payload.seller_contact_id,
            product_id=payload.product_id,
            qty=payload.qty,
            target_price=payload.target_price,
            origin_search_event_id=payload.origin_search_event_id,
            created_by=created_by,
        )

    async def update_deal(
        self, deal_id: uuid.UUID, payload: DealUpdateRequest
    ) -> Deal | None:
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return await self._deals.get(deal_id)
        return await self._deals.update(deal_id, **updates)

    async def get_deal(self, deal_id: uuid.UUID) -> Deal | None:
        return await self._deals.get(deal_id)

    async def list_deals(
        self, *, status: str | None = None, page: int = 1, page_size: int = 50
    ) -> tuple[list[Deal], int]:
        offset = (page - 1) * page_size
        return await self._deals.list_by_status(
            status=status, limit=page_size, offset=offset
        )

    # -------------------------------------------------------- product catalog

    async def create_product(self, payload: ProductCreateRequest) -> Product:
        repo = ProductRepository(self._session)
        return await repo.create(
            brand=payload.brand,
            family=payload.family,
            canonical_name=payload.canonical_name.lower(),
            tier=payload.tier,
            is_active=payload.is_active,
        )

    async def update_product(
        self, product_id: uuid.UUID, payload: ProductUpdateRequest
    ) -> Product | None:
        repo = ProductRepository(self._session)
        updates = payload.model_dump(exclude_unset=True)
        if "canonical_name" in updates:
            updates["canonical_name"] = updates["canonical_name"].lower()
        return await repo.update(product_id, **updates)

    async def list_products(
        self,
        *,
        brand: str | None = None,
        family: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Product], int]:
        repo = ProductRepository(self._session)
        offset = (page - 1) * page_size
        return await repo.list_active(brand=brand, family=family, limit=page_size, offset=offset)

    async def get_product(self, product_id: uuid.UUID) -> Product | None:
        repo = ProductRepository(self._session)
        return await repo.get(product_id)

    async def get_contact_product_tags(
        self, contact_id: uuid.UUID
    ) -> list[dict]:
        return await ContactProductTagRepository(self._session).list_for_contact(
            contact_id
        )

    # -------------------------------------------------------- training export

    async def export_training(self, *, since: datetime | None = None) -> list[dict]:
        """Export training records: search_event → outreach → deal chain (DSD §7.4)."""
        clauses: list[Any] = []
        if since:
            clauses.append(SearchEvent.executed_at >= since)

        stmt = sa.select(SearchEvent).order_by(SearchEvent.executed_at.desc()).limit(500)
        if clauses:
            stmt = stmt.where(*clauses)

        result = await self._session.execute(stmt)
        events = result.scalars().all()

        records: list[dict] = []
        for se in events:
            outreach_rows = await OutreachSendRepository(
                self._session
            ).list_for_search_event(se.id)
            deal_rows = await DealRepository(self._session).get_for_export(
                search_event_ids=[se.id]
            )

            records.append(
                TrainingExportRecord(
                    search_event_id=se.id,
                    user_id=se.user_id,
                    executed_at=se.executed_at,
                    query_text=se.query_text,
                    resolved_products=(
                        [str(p) for p in se.resolved_product_ids]
                        if se.resolved_product_ids
                        else []
                    ),
                    surfaced_buy=[],
                    surfaced_sell=[],
                    selected_contacts=[o.contact_id for o in outreach_rows],
                    templates_sent=[o.rendered_body or "" for o in outreach_rows],
                    deals=[
                        {
                            "deal_id": str(d.id),
                            "product": str(d.product_id) if d.product_id else None,
                            "status": d.status,
                        }
                        for d in deal_rows
                    ],
                    timings={"exported_at": datetime.now(tz=UTC).isoformat()},
                ).model_dump(mode="json")
            )
        return records


# ==============================================================================
# Classification service (sync — Celery path, LLM fallback)
# ==============================================================================


class MarketClassificationService:
    """LLM fallback classifier for low-confidence messages (DSD §4.2).

    Runs from a Celery task against a sync session. Uses Haiku via
    asyncio.run bridge (architectural invariant #12).
    """

    @staticmethod
    def classify_with_llm_sync(
        session: SyncSession,
        message_id: uuid.UUID,
    ) -> None:
        """LLM fallback: call Claude Haiku to classify side + extract products."""
        msg = session.get(MarketMessage, message_id)
        if msg is None:
            return

        # Only classify messages that need it.

        existing = session.execute(
            sa.select(sa.func.count()).select_from(MarketMessageProduct).where(
                MarketMessageProduct.market_message_id == message_id
            )
        ).scalar_one()
        if existing > 0:
            return  # Already classified by keywords.

        settings = get_settings()
        if not settings.ANTHROPIC_API_KEY:
            return  # No AI key configured — skip LLM fallback.

        import asyncio

        async def _call_llm() -> dict | None:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY,
                timeout=30,
            )
            try:
                response = await client.messages.create(
                    model=settings.AI_MODEL_BULK,
                    max_tokens=512,
                    system=_CLASSIFICATION_SYSTEM_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": f"Message text:\n{msg.raw_text}",
                    }],
                )
                text = "".join(
                    getattr(block, "text", "")
                    for block in response.content
                    if getattr(block, "type", None) == "text"
                )
                # Parse JSON from response.
                import json as _json
                try:
                    # Try to extract JSON object from response.
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start >= 0 and end > start:
                        return _json.loads(text[start:end])
                except Exception:
                    pass
                return None
            except Exception:
                return None
            finally:
                await client.close()

        result = asyncio.run(_call_llm())
        if result is None:
            return

        # Apply LLM results.
        llm_side = result.get("side", MarketSide.UNKNOWN.value)
        if llm_side in (MarketSide.BUY.value, MarketSide.SELL.value):
            session.execute(
                sa.update(MarketMessage)
                .where(MarketMessage.id == message_id)
                .values(side=llm_side)
            )

        # Overall LLM confidence, floored.
        llm_overall = float(result.get("confidence", 0.7))
        llm_overall = max(llm_overall, LLM_CONFIDENCE_FLOOR)

        products_data = result.get("products", [])
        if not isinstance(products_data, list):
            products_data = []

        min_product_conf = 1.0
        for pd in products_data:
            if not isinstance(pd, dict):
                continue
            name: str = str(pd.get("name", "")).lower().strip()
            if not name:
                continue
            # Resolve to known product or create alias.
            prod: Product | None = session.execute(
                sa.select(Product).where(
                    sa.func.lower(Product.canonical_name) == name
                )
            ).scalar_one_or_none()

            if prod is None:
                # Try alias resolution.
                alias_row = session.execute(
                    sa.select(ProductAlias).where(
                        sa.func.lower(ProductAlias.alias) == name
                    )
                ).scalar_one_or_none()
                if alias_row is not None:
                    prod = session.get(Product, alias_row.product_id)

            if prod is None:
                continue

            # Per-field confidence: side from overall, product from item if present.
            prod_conf_raw = pd.get("confidence")
            try:
                prod_conf = float(prod_conf_raw) if prod_conf_raw is not None else llm_overall
            except (ValueError, TypeError):
                prod_conf = llm_overall
            prod_conf = max(prod_conf, LLM_CONFIDENCE_FLOOR)
            row_confidence = min(llm_overall, prod_conf)
            if row_confidence < min_product_conf:
                min_product_conf = row_confidence

            per_field_conf = {"side": llm_overall, "product": prod_conf}
            import json as _json_mod
            attrs_json = _json_mod.dumps({"_confidence": per_field_conf})

            # Create resolution.
            prod_id = prod.id
            mmp_id = uuid.uuid4()
            session.execute(
                sa.text(
                    "INSERT INTO market_message_products "
                    "(id, market_message_id, product_id, qty, unit_price, "
                    "currency, spec, condition, grade, color, attributes, confidence, resolver, created_at) "
                    "VALUES (:id, :mid, :pid, :qty, :price, :currency, :spec, "
                    ":condition, :grade, :color, :attrs, :confidence, :resolver, :now) "
                    "ON CONFLICT (market_message_id, product_id) DO NOTHING"
                ),
                {
                    "id": mmp_id,
                    "mid": message_id,
                    "pid": prod_id,
                    "qty": pd.get("qty"),
                    "price": pd.get("price"),
                    "currency": pd.get("currency"),
                    "spec": pd.get("spec"),
                    "condition": pd.get("condition"),
                    "grade": pd.get("grade"),
                    "color": pd.get("color"),
                    "attrs": attrs_json,
                    "confidence": row_confidence,
                    "resolver": ResolverKind.LLM.value,
                    "now": datetime.now(tz=UTC),
                },
            )

            # Update contact product tag (guard applies inside).
            if msg.contact_id:
                cpt_repo: ContactProductTagRepository = ContactProductTagRepository(session)  # type: ignore[arg-type]
                cpt_repo.increment_tag_sync(
                    contact_id=msg.contact_id,
                    product_id=prod_id,
                    side=llm_side,
                    confidence=row_confidence,
                )

            # Alias-learning: persist novel spelling (DSD §4.3).
            existing_alias = session.execute(
                sa.select(ProductAlias).where(
                    ProductAlias.product_id == prod_id,
                    sa.func.lower(ProductAlias.alias) == name,
                )
            ).scalar_one_or_none()
            if existing_alias is None:
                session.execute(
                    pg_insert(ProductAlias)
                    .values(product_id=prod_id, alias=name, source="llm_learned")
                    .on_conflict_do_nothing(
                        index_elements=["product_id", "alias"]
                    )
                )

        # Three-band confidence routing (Phase 4).
        from app.modules.settings.repository import get_numeric_setting_sync

        auto_min = get_numeric_setting_sync(
            session, "market.confidence.auto_min", default=0.85
        )
        review_min = get_numeric_setting_sync(
            session, "market.confidence.review_min", default=0.55
        )

        if products_data:
            if min_product_conf >= auto_min:
                msg.review_status = ReviewStatus.AUTO.value
            elif min_product_conf >= review_min:
                msg.review_status = ReviewStatus.PENDING.value
            else:
                msg.review_status = ReviewStatus.AUTO.value
                # Flag existing resolutions as unresolved.
                existing_mmps = session.execute(
                    sa.select(MarketMessageProduct).where(
                        MarketMessageProduct.market_message_id == message_id
                    )
                ).scalars().all()
                for r in existing_mmps:
                    attrs = dict(r.attributes or {})
                    attrs["_unresolved"] = True
                    r.attributes = attrs
        # else: no products resolved — keep default review_status (AUTO)

        session.flush()


# ==============================================================================
# Review queue service (Phase 5)
# ==============================================================================


class MarketReviewService:
    """Review queue: list pending, resolve with corrections, dismiss, stats."""

    _MMP_COLUMNS: frozenset[str] = frozenset({
        "qty", "unit_price", "currency", "color", "condition", "grade", "spec",
    })

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._mm = MarketMessageRepository(session)
        self._mmp = MarketMessageProductRepository(session)
        self._cpt = ContactProductTagRepository(session)
        self._aliases = ProductAliasRepository(session)
        self._products = ProductRepository(session)

    # ------------------------------------------------------------------ listing

    async def list_pending(
        self, cursor: str | None, limit: int
    ) -> tuple[list[dict], str | None]:
        """Return (items as dicts, next_cursor base64 or None)."""
        import base64 as _b64

        cursor_expires_at: datetime | None = None
        cursor_id: uuid.UUID | None = None
        if cursor:
            try:
                decoded = _b64.urlsafe_b64decode(cursor.encode()).decode()
                parts = decoded.split("|", 1)
                cursor_expires_at = datetime.fromisoformat(parts[0])
                cursor_id = uuid.UUID(parts[1])
            except (ValueError, IndexError):
                cursor_expires_at = None
                cursor_id = None

        messages = await self._mm.list_pending(
            cursor_expires_at=cursor_expires_at,
            cursor_id=cursor_id,
            limit=limit,
        )

        if not messages:
            return [], None

        # Load product resolutions + product names for all returned messages.
        msg_ids = [m.id for m in messages]
        all_res = await self._mmp.list_for_messages(msg_ids)
        res_by_msg: dict[uuid.UUID, list[MarketMessageProduct]] = {}
        for r in all_res:
            res_by_msg.setdefault(r.market_message_id, []).append(r)

        # Collect all product IDs to fetch names.
        all_pids = {r.product_id for r in all_res}
        prod_names: dict[uuid.UUID, str] = {}
        if all_pids:
            p_result = await self._session.execute(
                sa.select(Product.id, Product.canonical_name).where(
                    Product.id.in_(list(all_pids))
                )
            )
            for pid, pname in p_result:
                prod_names[pid] = pname

        items: list[dict] = []
        for msg in messages:
            resolutions = res_by_msg.get(msg.id, [])
            field_confidences: dict[str, dict] = {}
            for r in resolutions:
                attrs = r.attributes or {}
                fc = attrs.get("_confidence")
                if isinstance(fc, dict):
                    field_confidences[str(r.product_id)] = fc

            item = {
                "id": msg.id,
                "source_type": msg.source_type,
                "source_id": msg.source_id,
                "sender_raw": msg.sender_raw,
                "contact_id": msg.contact_id,
                "contact_name": msg.contact.name if msg.contact else None,
                "side": msg.side,
                "raw_text": msg.raw_text,
                "normalized_text": msg.normalized_text,
                "captured_at": msg.captured_at,
                "expires_at": msg.expires_at,
                "status": msg.status,
                "review_status": msg.review_status,
                "created_at": msg.created_at,
                "products": [
                    {
                        "id": r.id,
                        "product_id": r.product_id,
                        "product_name": prod_names.get(r.product_id, ""),
                        "qty": r.qty,
                        "unit_price": r.unit_price,
                        "currency": r.currency,
                        "spec": r.spec,
                        "condition": r.condition,
                        "grade": r.grade,
                        "color": r.color,
                        "attributes": r.attributes,
                        "confidence": float(r.confidence),
                        "resolver": r.resolver,
                    }
                    for r in resolutions
                ],
                "field_confidences": field_confidences,
            }
            items.append(item)

        # Build next cursor from the last item.
        last = messages[-1]
        next_raw = f"{last.expires_at.isoformat()}|{last.id}"
        next_cursor = _b64.urlsafe_b64encode(next_raw.encode()).decode()

        return items, next_cursor

    # --------------------------------------------------------------- resolution

    async def resolve(
        self,
        message_id: uuid.UUID,
        payload,
        *,
        actor_id: uuid.UUID,
    ) -> MarketMessage:
        """Resolve a PENDING message with corrections. All effects in one
        transaction: update side + resolutions → set REVIEWED → write teach
        entries → apply deferred contact tags → audit."""
        from sqlalchemy.exc import IntegrityError

        msg = await self._mm.get_or_404(message_id)
        if msg.review_status != ReviewStatus.PENDING.value:
            raise ValueError("Only PENDING messages can be resolved.")

        audit_before = self._snapshot(msg)

        try:
            return await self._apply_resolve(message_id, msg, payload, actor_id, audit_before)
        except IntegrityError as exc:
            raise ValueError(f"Referenced entity does not exist: {exc}") from exc

    async def correct(
        self,
        message_id: uuid.UUID,
        payload,
        *,
        actor_id: uuid.UUID,
    ) -> MarketMessage:
        """Correct ANY message retroactively — no PENDING restriction.
        Used by the data-table view to fix AUTO-classified errors."""
        from sqlalchemy.exc import IntegrityError

        msg = await self._mm.get_or_404(message_id)

        audit_before = self._snapshot(msg)

        try:
            return await self._apply_resolve(
                message_id, msg, payload, actor_id, audit_before,
                action="corrected",
            )
        except IntegrityError as exc:
            raise ValueError(f"Referenced entity does not exist: {exc}") from exc

    async def _apply_resolve(
        self,
        message_id: uuid.UUID,
        msg: MarketMessage,
        payload,
        actor_id: uuid.UUID,
        audit_before: dict,
        *,
        action: str = "review_resolved",
    ) -> MarketMessage:
        from app.modules.audit.constants import ActorType

        changes: list[str] = []

        # 1. Update side if corrected.
        if payload.corrected_side and payload.corrected_side != msg.side:
            if payload.corrected_side in (
                MarketSide.BUY.value,
                MarketSide.SELL.value,
                MarketSide.MIXED.value,
            ):
                msg.side = payload.corrected_side
                msg.expires_at = _compute_expiry(
                    payload.corrected_side, msg.captured_at
                )
                changes.append("side")

        # 2. Update / insert MarketMessageProduct rows.
        seen_pids: set[uuid.UUID] = set()
        for fix in payload.resolutions:
            # Find existing MMP for this message + product.
            existing = await self._session.execute(
                sa.select(MarketMessageProduct).where(
                    MarketMessageProduct.market_message_id == message_id,
                    MarketMessageProduct.product_id == fix.product_id,
                )
            )
            mmp_row = existing.scalar_one_or_none()

            if mmp_row is not None:
                updated = False
                jsonb_attrs: dict = {}
                if fix.attributes:
                    for key, val in fix.attributes.items():
                        if key in self._MMP_COLUMNS:
                            setattr(mmp_row, key, val)
                            updated = True
                        elif key.startswith("_"):
                            # Internal keys (_confidence, etc.) — skip, not
                            # settable by human review.
                            pass
                        else:
                            jsonb_attrs[key] = val
                            updated = True
                    if jsonb_attrs:
                        existing_attrs = dict(mmp_row.attributes or {})
                        existing_attrs.update(jsonb_attrs)
                        mmp_row.attributes = existing_attrs
                if updated:
                    changes.append(f"resolution:{fix.product_id}")
            elif fix.attributes:
                # Split known columns from JSONB extras for the new row.
                col_attrs = {}
                jsonb_extras = {}
                for key, val in fix.attributes.items():
                    if key in self._MMP_COLUMNS:
                        col_attrs[key] = val
                    elif key.startswith("_"):
                        pass
                    else:
                        jsonb_extras[key] = val
                await self._mmp.create(
                    market_message_id=message_id,
                    product_id=fix.product_id,
                    qty=col_attrs.get("qty"),
                    unit_price=col_attrs.get("unit_price"),
                    currency=col_attrs.get("currency"),
                    color=col_attrs.get("color"),
                    condition=col_attrs.get("condition"),
                    grade=col_attrs.get("grade"),
                    spec=col_attrs.get("spec"),
                    attributes=jsonb_extras if jsonb_extras else None,
                    confidence=1.0,
                    resolver=ResolverKind.KEYWORD.value,
                )
                changes.append(f"resolution:{fix.product_id}")

            seen_pids.add(fix.product_id)

        # 3. Set review_status = REVIEWED.
        msg.review_status = ReviewStatus.REVIEWED.value
        changes.append("review_status")

        # 4. Write teach entries. Use 'human' source for corrections,
        #    'llm_learned' for review-queue resolves (existing behavior).
        teach_source = (
            AliasSource.HUMAN.value if action == "corrected"
            else AliasSource.LLM_LEARNED.value
        )
        for t in payload.teach:
            if t.kind == "product":
                prod = await self._products.get_by_canonical_name(
                    t.canonical.lower()
                )
                if prod is not None:
                    await self._session.execute(
                        pg_insert(ProductAlias).values(
                            product_id=prod.id,
                            alias=t.alias.lower(),
                            source=teach_source,
                        ).on_conflict_do_update(
                            index_elements=["product_id", "alias"],
                            set_={"source": teach_source},
                        )
                    )
                    changes.append(f"teach:product:{t.alias}->{t.canonical}")
            else:
                _logger = logging.getLogger(__name__)
                _logger.info(
                    "Teach entry kind=%s skipped (P7 vocab not yet landed): %s→%s",
                    t.kind, t.alias, t.canonical,
                )

        # 5. Apply deferred increment_tag for each resolution.
        #    Done with direct Core SQL so we don't call
        #    ContactProductTagRepository._read_auto_min inside the
        #    async session (avoids a MissingGreenlet path through the
        #    AppSetting query in the test environment).
        if msg.contact_id:
            all_res = await self._mmp.list_for_message(message_id)
            now = datetime.now(tz=UTC)
            buy_delta = 1 if msg.side == MarketSide.BUY.value else 0
            sell_delta = 1 if msg.side == MarketSide.SELL.value else 0
            for r in all_res:
                await self._session.execute(
                    pg_insert(ContactProductTag)
                    .values(
                        contact_id=msg.contact_id,
                        product_id=r.product_id,
                        side_buy_count=buy_delta,
                        side_sell_count=sell_delta,
                        observation_count=1,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["contact_id", "product_id"],
                        set_={
                            "side_buy_count": ContactProductTag.side_buy_count
                            + buy_delta,
                            "side_sell_count": ContactProductTag.side_sell_count
                            + sell_delta,
                            "observation_count": ContactProductTag.observation_count
                            + 1,
                            "last_seen_at": now,
                        },
                    )
                )

        # 6. Write audit_logs row.
        audit_after = self._snapshot(msg)
        await self._session.execute(
            sa.text(
                "INSERT INTO audit_logs "
                "(actor_type, actor_id, action, entity_type, entity_id, "
                " before_state, after_state, created_at, updated_at) "
                "VALUES (:actor_type, :actor_id, :action, :entity_type, :entity_id, "
                " CAST(:before_state AS jsonb), CAST(:after_state AS jsonb), "
                " :now, :now)"
            ),
            {
                "actor_type": ActorType.USER.value,
                "actor_id": actor_id,
                "action": action,
                "entity_type": "market_messages",
                "entity_id": message_id,
                "before_state": json.dumps(audit_before),
                "after_state": json.dumps(audit_after),
                "now": datetime.now(tz=UTC),
            },
        )
        changes.append("audit")

        await self._session.flush()
        return msg

    # ---------------------------------------------------------------- dismiss

    async def dismiss(
        self,
        message_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> MarketMessage:
        """Dismiss a PENDING message. No contact writes."""
        from app.modules.audit.constants import ActorType

        msg = await self._mm.get_or_404(message_id)
        if msg.review_status != ReviewStatus.PENDING.value:
            raise ValueError("Only PENDING messages can be dismissed.")

        audit_before = self._snapshot(msg)
        msg.review_status = ReviewStatus.DISMISSED.value
        audit_after = {"review_status": ReviewStatus.DISMISSED.value}

        await self._session.execute(
            sa.text(
                "INSERT INTO audit_logs "
                "(actor_type, actor_id, action, entity_type, entity_id, "
                " before_state, after_state, created_at, updated_at) "
                "VALUES (:actor_type, :actor_id, :action, :entity_type, :entity_id, "
                " CAST(:before_state AS jsonb), CAST(:after_state AS jsonb), "
                " :now, :now)"
            ),
            {
                "actor_type": ActorType.USER.value,
                "actor_id": actor_id,
                "action": "review_dismissed",
                "entity_type": "market_messages",
                "entity_id": message_id,
                "before_state": json.dumps(audit_before),
                "after_state": json.dumps(audit_after),
                "now": datetime.now(tz=UTC),
            },
        )

        await self._session.flush()
        return msg

    # ------------------------------------------------------------------- stats

    async def get_stats(self) -> dict:
        raw = await self._mm.get_review_stats_raw()
        median = raw["median_review_seconds"]
        queue_depth = raw["queue_depth"]
        capacity: float | None = None
        if median is not None and queue_depth > 0:
            capacity = (median * queue_depth) / 10800.0
        return {
            **raw,
            "capacity_estimate": capacity,
        }

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _snapshot(msg: MarketMessage) -> dict:
        return {
            "id": str(msg.id),
            "side": msg.side,
            "review_status": msg.review_status,
            "expires_at": msg.expires_at.isoformat() if msg.expires_at else None,
        }


_CLASSIFICATION_SYSTEM_PROMPT = """\
You classify WhatsApp marketplace messages. Output ONLY a JSON object with no other text.

The JSON must have:
- "side": "BUY" or "SELL" or "UNKNOWN"
- "confidence": a number 0.0-1.0
- "products": a list of objects, each with:
    "name": canonical product name (lowercase, e.g. "iphone 16 pro max")
    "qty": integer or null
    "price": number or null
    "currency": string or null (e.g. "AED")
    "spec": string or null (e.g. "256GB")
    "condition": string or null (e.g. "new", "used")
    "grade": string or null (e.g. "A", "B", "C")
    "color": string or null

BUY signals: "wtb", "want to buy", "looking for", "need", "buy", "ISO", "searching for"
SELL signals: "wts", "selling", "for sale", "available", "brand new", "sealed", "in stock"

Only include products that are actually mentioned. If no products are found, return an empty list.

Example output:
{"side": "BUY", "confidence": 0.9, "products": [{"name": "iphone 16 pro max", "qty": 1, "price": null, "currency": null, "spec": "256GB", "condition": "new", "grade": "A", "color": "black"}]}"""
