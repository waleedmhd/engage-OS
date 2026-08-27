"""Market intelligence models (DSD §3).

Tables in the ``crm`` schema (D10.1: market module owns crm-schema tables).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.market.constants import (
    AliasSource,
    DealStage,
    MarketSide,
    MessageSource,
    MessageStatus,
    OutreachStatus,
    ProductTier,
    ResolverKind,
    ReviewStatus,
)

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.contacts.models import Contact
    from app.modules.templates.models import Template


# --------------------------------------------------------------------------- #
# §3.1 — Ingestion
# --------------------------------------------------------------------------- #


class MarketMessage(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "market_messages"
    __table_args__ = (
        enum_check("source_type", MessageSource, "ck_market_messages_source_type_valid"),
        enum_check("side", MarketSide, "ck_market_messages_side_valid"),
        enum_check("status", MessageStatus, "ck_market_messages_status_valid"),
        enum_check("review_status", ReviewStatus, "ck_market_messages_review_status_valid"),
        Index("ix_market_messages_status_side_captured", "status", "side", "captured_at"),
        Index("ix_market_messages_contact_id", "contact_id"),
        Index("ix_market_messages_expires_at", "expires_at"),
        Index("ix_market_messages_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sender_raw: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    side: Mapped[str] = mapped_column(
        String(8), nullable=False, default=MarketSide.UNKNOWN.value, index=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MessageStatus.ACTIVE.value, index=True
    )
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ReviewStatus.AUTO.value, index=True
    )
    dedup_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    msg_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    extracted_attributes: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="Precomputed Pass B+C output — source depends on MARKET_TRUST_LISTENER",
    )
    seen_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    source_groups: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb")
    )

    contact: Mapped[Contact | None] = relationship("Contact")
    product_resolutions: Mapped[list[MarketMessageProduct]] = relationship(
        "MarketMessageProduct", back_populates="market_message", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# §3.2 — Products & aliases
# --------------------------------------------------------------------------- #


class Product(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        enum_check("tier", ProductTier, "ck_products_tier_valid"),
        Index("ix_products_brand_family", "brand", "family"),
        Index("ix_products_is_active", "is_active"),
    )

    brand: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canonical_name: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True, index=True
    )
    tier: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ProductTier.UNKNOWN.value
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    aliases: Mapped[list[ProductAlias]] = relationship(
        "ProductAlias", back_populates="product", cascade="all, delete-orphan"
    )
    message_resolutions: Mapped[list[MarketMessageProduct]] = relationship(
        "MarketMessageProduct", back_populates="product"
    )
    contact_tags: Mapped[list[ContactProductTag]] = relationship(
        "ContactProductTag", back_populates="product", cascade="all, delete-orphan"
    )


class ProductAlias(Base):
    __tablename__ = "product_aliases"
    __table_args__ = (
        enum_check("source", AliasSource, "ck_product_aliases_source_valid"),
        UniqueConstraint("product_id", "alias", name="uq_product_aliases_product_alias"),
        Index("ix_product_aliases_alias", "alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AliasSource.SEED.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped[Product] = relationship("Product", back_populates="aliases")


# --------------------------------------------------------------------------- #
# §3.2 — Per-message product resolution ("other data")
# --------------------------------------------------------------------------- #


class MarketMessageProduct(UUIDPKMixin, Base):
    __tablename__ = "market_message_products"
    __table_args__ = (
        enum_check("resolver", ResolverKind, "ck_market_message_products_resolver_valid"),
        UniqueConstraint(
            "market_message_id", "product_id",
            name="uq_mmp_message_product",
        ),
        Index("ix_mmp_message_id", "market_message_id"),
        Index("ix_mmp_product_id", "product_id"),
    )

    market_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("market_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    spec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(8), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=False, default=0.0
    )
    resolver: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ResolverKind.KEYWORD.value
    )
    side: Mapped[str | None] = mapped_column(String(8), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    market_message: Mapped[MarketMessage] = relationship(
        "MarketMessage", back_populates="product_resolutions"
    )
    product: Mapped[Product] = relationship("Product", back_populates="message_resolutions")


# --------------------------------------------------------------------------- #
# §3.3 — Derived product tags per contact
# --------------------------------------------------------------------------- #


class ContactProductTag(Base):
    __tablename__ = "contact_product_tags"
    __table_args__ = (
        PrimaryKeyConstraint("contact_id", "product_id", name="pk_contact_product_tags"),
        Index("ix_contact_product_tags_product_id", "product_id"),
        Index("ix_contact_product_tags_last_seen", "last_seen_at"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    side_buy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    side_sell_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    contact: Mapped[Contact] = relationship("Contact")
    product: Mapped[Product] = relationship("Product", back_populates="contact_tags")


# --------------------------------------------------------------------------- #
# §3.4 — Search persistence
# --------------------------------------------------------------------------- #


class SavedSearch(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "saved_searches"
    __table_args__ = (Index("ix_saved_searches_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_product_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        JSONB, nullable=True
    )
    filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped[User] = relationship("User")


class SearchEvent(UUIDPKMixin, Base):
    __tablename__ = "search_events"
    __table_args__ = (
        Index("ix_search_events_user_executed", "user_id", "executed_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_product_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        JSONB, nullable=True
    )
    filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    buy_result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sell_result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User | None] = relationship("User")


# --------------------------------------------------------------------------- #
# §3.5 — Outreach & deal pipeline (training chain)
# --------------------------------------------------------------------------- #


class OutreachSend(UUIDPKMixin, Base):
    __tablename__ = "outreach_sends"
    __table_args__ = (
        enum_check("status", OutreachStatus, "ck_outreach_sends_status_valid"),
        Index("ix_outreach_sends_search_event", "search_event_id"),
        Index("ix_outreach_sends_contact", "contact_id"),
    )

    search_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("search_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    market_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("market_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    rendered_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OutreachStatus.QUEUED.value, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    search_event: Mapped[SearchEvent | None] = relationship("SearchEvent")
    contact: Mapped[Contact] = relationship("Contact")
    market_message: Mapped[MarketMessage | None] = relationship("MarketMessage")
    template: Mapped[Template | None] = relationship("Template")
    sender: Mapped[User | None] = relationship("User", foreign_keys=[sent_by])


class Deal(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "deals"
    __table_args__ = (
        enum_check("status", DealStage, "ck_deals_status_valid"),
        Index("ix_deals_status", "status"),
        Index("ix_deals_origin_search_event", "origin_search_event_id"),
    )

    buyer_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    seller_contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DealStage.MATCHED.value, index=True
    )
    origin_search_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("search_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    buyer_contact: Mapped[Contact | None] = relationship(
        "Contact", foreign_keys=[buyer_contact_id]
    )
    seller_contact: Mapped[Contact | None] = relationship(
        "Contact", foreign_keys=[seller_contact_id]
    )
    product: Mapped[Product | None] = relationship("Product")
    origin_search_event: Mapped[SearchEvent | None] = relationship("SearchEvent")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])


# --------------------------------------------------------------------------- #
# §3.7 — Attribute vocabulary (Phase 7)
# --------------------------------------------------------------------------- #


class AttributeVocab(Base):
    __tablename__ = "attribute_vocab"
    __table_args__ = (
        UniqueConstraint("category", "tag", name="uq_attribute_vocab_category_tag"),
        Index("idx_av_category", "category"),
        Index("idx_av_kind", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    tag: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()
    )
