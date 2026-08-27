"""Contact intelligence service — builds per-contact market profiles from historical data."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market.constants import MarketSide
from app.modules.market.models import (
    ContactProductTag,
    MarketMessage,
    MarketMessageProduct,
    Product,
)

# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #


@dataclass
class ProductInterest:
    product_id: str
    product_name: str
    brand: str
    family: str | None
    buy_count: int
    sell_count: int
    observation_count: int
    first_seen: datetime
    last_seen: datetime


@dataclass
class AttributePreference:
    """Aggregated attribute preferences across all of a contact's messages."""
    storage: list[tuple[str, int]] = field(default_factory=list)
    ram: list[tuple[str, int]] = field(default_factory=list)
    color: list[tuple[str, int]] = field(default_factory=list)
    region: list[tuple[str, int]] = field(default_factory=list)
    condition: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class PriceRange:
    min_unit_price: float | None
    max_unit_price: float | None
    currency: str | None


@dataclass
class ContactIntelligence:
    contact_id: str
    contact_name: str | None
    total_messages: int
    buy_messages: int
    sell_messages: int
    active_since: datetime | None
    last_active: datetime | None
    products: list[ProductInterest]
    attribute_preferences: AttributePreference
    price_range: PriceRange


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class ContactIntelligenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_intelligence(self, contact_id: uuid.UUID) -> ContactIntelligence:
        """Build full intelligence profile for a contact."""

        # 1. Aggregate message stats from market_messages.
        msg_stats = await self._session.execute(
            sa.select(
                sa.func.count().label("total"),
                sa.func.count().filter(MarketMessage.side == MarketSide.BUY.value).label("buy"),
                sa.func.count().filter(MarketMessage.side == MarketSide.SELL.value).label("sell"),
                sa.func.min(MarketMessage.captured_at).label("first"),
                sa.func.max(MarketMessage.captured_at).label("last"),
            ).where(MarketMessage.contact_id == contact_id)
        )
        row = msg_stats.one()
        total = int(row.total or 0)
        buy = int(row.buy or 0)
        sell = int(row.sell or 0)
        active_since: datetime | None = row.first
        last_active: datetime | None = row.last

        # 2. Load ContactProductTag rows with product names.
        tag_rows = await self._session.execute(
            sa.select(ContactProductTag, Product)
            .join(Product, ContactProductTag.product_id == Product.id)
            .where(ContactProductTag.contact_id == contact_id)
            .order_by(ContactProductTag.last_seen_at.desc())
        )
        products: list[ProductInterest] = []
        for cpt, prod in tag_rows:
            products.append(ProductInterest(
                product_id=str(cpt.product_id),
                product_name=prod.canonical_name,
                brand=prod.brand,
                family=prod.family,
                buy_count=cpt.side_buy_count,
                sell_count=cpt.side_sell_count,
                observation_count=cpt.observation_count,
                first_seen=cpt.first_seen_at,
                last_seen=cpt.last_seen_at,
            ))

        # 3. Aggregate extracted_attributes across all messages.
        attr_rows = await self._session.execute(
            sa.select(MarketMessage.extracted_attributes)
            .where(
                MarketMessage.contact_id == contact_id,
                MarketMessage.extracted_attributes.is_not(None),
            )
        )
        prefs = self._aggregate_attributes(attr_rows.scalars().all())

        # 4. Compute price_range from MarketMessageProduct.unit_price.
        price_result = await self._session.execute(
            sa.select(
                sa.func.min(MarketMessageProduct.unit_price),
                sa.func.max(MarketMessageProduct.unit_price),
                sa.func.mode().within_group(
                    MarketMessageProduct.currency
                ),
            )
            .select_from(MarketMessage)
            .join(
                MarketMessageProduct,
                MarketMessageProduct.market_message_id == MarketMessage.id,
            )
            .where(
                MarketMessage.contact_id == contact_id,
                MarketMessageProduct.unit_price.is_not(None),
            )
        )
        p_row = price_result.one()
        price_range = PriceRange(
            min_unit_price=float(p_row[0]) if p_row[0] is not None else None,
            max_unit_price=float(p_row[1]) if p_row[1] is not None else None,
            currency=p_row[2],
        )

        # Load contact name.
        from app.modules.contacts.models import Contact
        contact_result = await self._session.execute(
            sa.select(Contact.name).where(Contact.id == contact_id)
        )
        contact_name = contact_result.scalar_one_or_none()

        return ContactIntelligence(
            contact_id=str(contact_id),
            contact_name=contact_name,
            total_messages=total,
            buy_messages=buy,
            sell_messages=sell,
            active_since=active_since,
            last_active=last_active,
            products=products,
            attribute_preferences=prefs,
            price_range=price_range,
        )

    async def get_contacts_ranked(
        self,
        *,
        side: str | None = None,
        product_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Rank contacts by activity volume for a given side/product."""
        clauses: list = []
        if side:
            clauses.append(MarketMessage.side == side)
        if product_id:
            clauses.append(
                MarketMessage.id.in_(
                    sa.select(MarketMessageProduct.market_message_id).where(
                        MarketMessageProduct.product_id == product_id
                    )
                )
            )

        subq = (
            sa.select(
                MarketMessage.contact_id,
                sa.func.count().label("message_count"),
                sa.func.count().filter(MarketMessage.side == MarketSide.BUY.value).label("buy_count"),
                sa.func.count().filter(MarketMessage.side == MarketSide.SELL.value).label("sell_count"),
            )
            .where(
                MarketMessage.contact_id.is_not(None),
                *clauses,
            )
            .group_by(MarketMessage.contact_id)
            .order_by(sa.func.count().desc())
            .limit(limit)
            .subquery()
        )

        from app.modules.contacts.models import Contact
        rows = await self._session.execute(
            sa.select(
                subq.c.contact_id,
                subq.c.message_count,
                subq.c.buy_count,
                subq.c.sell_count,
                Contact.name,
            )
            .outerjoin(Contact, Contact.id == subq.c.contact_id)
            .order_by(subq.c.message_count.desc())
        )
        results: list[dict] = []
        for row in rows:
            cid = str(row.contact_id)
            # Load top 3 product names for the contact.
            top_prods = await self._session.execute(
                sa.select(Product.canonical_name)
                .select_from(ContactProductTag)
                .join(Product, ContactProductTag.product_id == Product.id)
                .where(ContactProductTag.contact_id == row.contact_id)
                .order_by(
                    (ContactProductTag.side_buy_count + ContactProductTag.side_sell_count).desc()
                )
                .limit(3)
            )
            results.append({
                "contact_id": cid,
                "contact_name": row.name,
                "message_count": int(row.message_count),
                "buy_count": int(row.buy_count),
                "sell_count": int(row.sell_count),
                "top_products": [p[0] for p in top_prods],
            })
        return results

    @staticmethod
    def _aggregate_attributes(rows: Sequence[Any]) -> AttributePreference:
        """Aggregate extracted_attributes JSONB across messages into counts."""
        storage: dict[str, int] = defaultdict(int)
        ram: dict[str, int] = defaultdict(int)
        color: dict[str, int] = defaultdict(int)
        region: dict[str, int] = defaultdict(int)
        condition: dict[str, int] = defaultdict(int)

        for row in rows:
            if not row or not isinstance(row, dict):
                continue
            # P8 extractor stores {intent: ..., attributes: {...}}
            # Listener stores precomputed block directly.
            attrs = row.get("attributes") or row

            for s in _as_list(attrs.get("storage")):
                storage[s] += 1
            for r in _as_list(attrs.get("ram")):
                ram[r] += 1
            for c in _as_list(attrs.get("color")):
                color[c] += 1
            for r in _as_list(attrs.get("region")):
                region[r] += 1
            for c in _as_list(attrs.get("condition")):
                condition[c] += 1

        def _sorted(items: dict[str, int]) -> list[tuple[str, int]]:
            return sorted(items.items(), key=lambda x: (-x[1], x[0]))

        return AttributePreference(
            storage=_sorted(storage),
            ram=_sorted(ram),
            color=_sorted(color),
            region=_sorted(region),
            condition=_sorted(condition),
        )


def _as_list(val: object) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)]
