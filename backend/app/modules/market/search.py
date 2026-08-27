"""Market search service — FTS-backed search, saved searches, search events (DSD §6-7)."""

from __future__ import annotations

import base64 as _b64
import json as _json
import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market.constants import MarketSide
from app.modules.market.models import (
    AttributeVocab,
    MarketMessageProduct,
    Product,
    SavedSearch,
    SearchEvent,
)
from app.modules.market.repository import (
    MarketMessageProductRepository,
    MarketMessageRepository,
    ProductAliasRepository,
    ProductRepository,
    SavedSearchRepository,
    SearchEventRepository,
)
from app.modules.market.schemas import (
    MarketMessageProductOut,
    MarketSearchCard,
    MarketSearchParams,
    MarketSearchResponse,
    ProductResponse,
    SavedSearchCreateRequest,
)


def _sanitize_query(q: str) -> str:
    """Remove characters that cause ``websearch_to_tsquery`` syntax errors."""
    return re.sub(r'[()&|!*]', '', q).strip()


def _encode_search_cursor(
    buy_ca: datetime | None,
    buy_id: uuid.UUID | None,
    sell_ca: datetime | None,
    sell_id: uuid.UUID | None,
) -> str | None:
    """Encode per-side keyset positions into a single base64 cursor."""
    payload: dict[str, list] = {}
    if buy_ca is not None and buy_id is not None:
        payload["b"] = [buy_ca.isoformat(), str(buy_id)]
    if sell_ca is not None and sell_id is not None:
        payload["s"] = [sell_ca.isoformat(), str(sell_id)]
    if not payload:
        return None
    return _b64.urlsafe_b64encode(_json.dumps(payload).encode()).decode()


def _decode_search_cursor(
    cursor: str | None,
) -> tuple[datetime | None, uuid.UUID | None, datetime | None, uuid.UUID | None]:
    """Decode a composite search cursor into per-side (captured_at, id) tuples."""
    if not cursor:
        return None, None, None, None
    try:
        payload = _json.loads(_b64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, TypeError, _json.JSONDecodeError):
        return None, None, None, None

    buy_ca, buy_id = None, None
    sell_ca, sell_id = None, None
    try:
        b = payload.get("b")
        if b and len(b) == 2:
            buy_ca = datetime.fromisoformat(b[0])
            buy_id = uuid.UUID(b[1])
    except (ValueError, TypeError):
        pass
    try:
        s = payload.get("s")
        if s and len(s) == 2:
            sell_ca = datetime.fromisoformat(s[0])
            sell_id = uuid.UUID(s[1])
    except (ValueError, TypeError):
        pass
    return buy_ca, buy_id, sell_ca, sell_id


class MarketSearchService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._mm = MarketMessageRepository(session)
        self._products = ProductRepository(session)
        self._aliases = ProductAliasRepository(session)
        self._mmp = MarketMessageProductRepository(session)
        self._saved = SavedSearchRepository(session)
        self._searches = SearchEventRepository(session)

    async def search(
        self, params: MarketSearchParams, *, user_id: uuid.UUID
    ) -> MarketSearchResponse:
        """Deterministic union retrieval (R6.1, R6.2) with keyset pagination."""
        q = _sanitize_query(params.q) if params.q else ""

        # Resolve query text to product IDs via alias match.
        resolved_ids: list[uuid.UUID] | None = None
        resolved_products: list[Product] = []
        if q:
            alias_matches = await self._aliases.resolve(q.lower())
            if alias_matches:
                resolved_ids = list({p.id for _, p in alias_matches})
                resolved_products = [p for _, p in alias_matches]
            # Also try direct product name match.
            if not resolved_ids:
                prod = await self._products.get_by_canonical_name(q.lower())
                if prod:
                    resolved_ids = [prod.id]
                    resolved_products = [prod]

        # Expand query with attribute vocab synonyms for broader FTS matching.
        expanded_q: str | None = None
        if q:
            expanded_q = await self._expand_query_vocab(q)

        # Merge product_ids from params with query-resolved ones.
        all_product_ids: list[uuid.UUID] | None = None
        if params.product_ids and resolved_ids:
            all_product_ids = list({*params.product_ids, *resolved_ids})
        elif params.product_ids:
            all_product_ids = params.product_ids
        elif resolved_ids:
            all_product_ids = resolved_ids

        # Decode composite cursor into per-side keyset positions.
        buy_ca, buy_cid, sell_ca, sell_cid = _decode_search_cursor(params.cursor)

        # Fetch BUY and SELL results separately for two-pane output (DSD §6.2).
        buy_messages, buy_total, buy_next_ca, buy_next_id = await self._mm.search_fts(
            q=q if q else None,
            expanded_q=expanded_q,
            side=MarketSide.BUY.value,
            product_ids=all_product_ids,
            brand=params.brand,
            family=params.family,
            condition=params.condition,
            grade=params.grade,
            limit=params.page_size,
            cursor_captured_at=buy_ca,
            cursor_id=buy_cid,
        )
        sell_messages, sell_total, sell_next_ca, sell_next_id = await self._mm.search_fts(
            q=q if q else None,
            expanded_q=expanded_q,
            side=MarketSide.SELL.value,
            product_ids=all_product_ids,
            brand=params.brand,
            family=params.family,
            condition=params.condition,
            grade=params.grade,
            limit=params.page_size,
            cursor_captured_at=sell_ca,
            cursor_id=sell_cid,
        )

        # Load product resolutions for all messages.
        all_msg_ids = [m.id for m in buy_messages] + [m.id for m in sell_messages]
        resolutions = await self._mmp.list_for_messages(all_msg_ids)
        res_by_msg: dict[uuid.UUID, list[MarketMessageProduct]] = {}
        for r in resolutions:
            res_by_msg.setdefault(r.market_message_id, []).append(r)

        def _to_cards(msgs: list) -> list[MarketSearchCard]:
            cards: list[MarketSearchCard] = []
            for msg in msgs:
                age_minutes = int(
                    (datetime.now(tz=UTC) - msg.captured_at).total_seconds() / 60
                )
                card_resolutions = res_by_msg.get(msg.id, [])

                products_out: list[MarketMessageProductOut] = []
                for r in card_resolutions:
                    products_out.append(
                        MarketMessageProductOut(
                            id=r.id,
                            product_id=r.product_id,
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
                    )

                cards.append(
                    MarketSearchCard(
                        market_message_id=msg.id,
                        contact_id=msg.contact_id,
                        contact_name=msg.contact.name if msg.contact else None,
                        sender_raw=msg.sender_raw,
                        raw_text=msg.raw_text,
                        side=msg.side,
                        captured_at=msg.captured_at,
                        freshness_minutes=age_minutes,
                        products=products_out,
                        seen_count=msg.seen_count or 1,
                        source_groups=msg.source_groups or [],
                    )
                )
            return cards

        # Build next cursor from per-side positions.
        next_cursor = _encode_search_cursor(
            buy_next_ca, buy_next_id, sell_next_ca, sell_next_id
        )
        has_more = (
            buy_next_ca is not None
            or sell_next_ca is not None
        )

        # Log search event (DSD §7.2).
        await self._searches.create(
            user_id=user_id,
            query_text=q,
            resolved_product_ids=all_product_ids,
            filters=params.model_dump(
                include={"brand", "family", "condition", "grade"}
            ),
            buy_result_count=buy_total,
            sell_result_count=sell_total,
        )

        return MarketSearchResponse(
            buy_items=_to_cards(buy_messages),
            sell_items=_to_cards(sell_messages),
            buy_total=buy_total,
            sell_total=sell_total,
            query_text=q,
            resolved_products=[
                ProductResponse.model_validate(p) for p in resolved_products
            ],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def _expand_query_vocab(self, q: str) -> str | None:
        """Expand query with related terms from attribute_vocab for FTS.

        Returns a query string suitable for ``websearch_to_tsquery`` that
        includes the original query OR'd with vocab aliases, or ``None``
        when no expansion applies.
        """
        result = await self._session.execute(
            sa.select(AttributeVocab).where(AttributeVocab.is_active == True)  # noqa: E712
        )
        entries = result.scalars().all()
        if not entries:
            return None

        q_lower = q.lower()
        q_tokens = set(q_lower.split())
        expansion_terms: set[str] = set()

        for entry in entries:
            all_terms: list[str] = [entry.canonical, *list(entry.aliases or [])]
            if any(term.lower() in q_lower or q_lower in term.lower() for term in all_terms):
                for t in all_terms:
                    stripped = t.strip()
                    if not stripped:
                        continue
                    if len(stripped) <= 1:
                        continue
                    if not re.search(r"[a-zA-Z0-9]", stripped):
                        continue
                    # Only skip if the exact term (or its token) is already in the query.
                    stripped_lower = stripped.lower()
                    if stripped_lower == q_lower or stripped_lower in q_tokens:
                        continue
                    expansion_terms.add(stripped)

        if not expansion_terms:
            return None

        or_parts: list[str] = []
        for term in sorted(expansion_terms, key=len, reverse=True):
            if " " in term:
                or_parts.append(f'"{term}"')
            else:
                or_parts.append(term)

        return f'{q} OR ({" OR ".join(or_parts)})'

    # ----------------------------------------------------------- saved searches

    async def save_search(
        self, payload: SavedSearchCreateRequest, *, user_id: uuid.UUID
    ) -> SavedSearch:
        return await self._saved.create(
            user_id=user_id,
            name=payload.name,
            query_text=payload.query_text,
            resolved_product_ids=payload.resolved_product_ids,
            filters=payload.filters,
        )

    async def list_saved_searches(
        self, user_id: uuid.UUID, *, page: int, page_size: int
    ) -> tuple[list[SavedSearch], int]:
        offset = (page - 1) * page_size
        return await self._saved.list_for_user(user_id, limit=page_size, offset=offset)

    async def delete_saved_search(self, search_id: uuid.UUID) -> bool:
        return await self._saved.delete(search_id)

    # ------------------------------------------------------------ search events

    async def list_search_events(
        self, user_id: uuid.UUID, *, page: int, page_size: int
    ) -> tuple[list[SearchEvent], int]:
        offset = (page - 1) * page_size
        return await self._searches.list_recent(
            user_id, limit=page_size, offset=offset
        )
