"""Market module Pydantic schemas (DSD section 6 through 8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Ingestion (DSD §3.1)
# --------------------------------------------------------------------------- #


class PrecomputedProduct(BaseModel):
    """Listener precomputed product hint — applied verbatim under trust flag."""
    hint: str = Field(min_length=1, max_length=200)
    qty: int | None = None
    unit_price: Decimal | None = Field(default=None, max_digits=19, decimal_places=4)
    currency: str | None = Field(default=None, max_length=8)
    storage: str | None = Field(default=None, max_length=32)
    color: str | None = Field(default=None, max_length=32)
    spec_region: str | None = Field(default=None, max_length=64)
    condition: str | None = Field(default=None, max_length=32)
    grade: str | None = Field(default=None, max_length=8)


class PrecomputedBlock(BaseModel):
    """Listener Pass B-D output, trusted during transition (Decision #2)."""
    version: str = Field(min_length=1, max_length=32)
    side: str = Field(min_length=1, max_length=8)
    attributes: dict | None = None
    products: list[PrecomputedProduct] = []
    risk_tags: list[str] | None = None


class MarketMessageIngest(BaseModel):
    """Signed POST body from the WhatsApp reader."""
    source_type: str = Field(min_length=1, max_length=16)
    source_id: str | None = Field(default=None, max_length=128)
    sender_raw: str | None = Field(default=None, max_length=64)
    raw_text: str = Field(min_length=1)
    captured_at: datetime
    dedup_hash: str = Field(min_length=1, max_length=64)
    group_name: str | None = Field(default=None, max_length=255)
    sender_name: str | None = Field(default=None, max_length=255)
    msg_type: str | None = Field(default=None, max_length=16)
    precomputed: PrecomputedBlock | None = None

    @field_validator("source_type")
    @classmethod
    def _normalize_source_type(cls, v: str) -> str:
        """Strip the ``whatsapp_`` prefix the listener attaches (P9)."""
        return v.removeprefix("whatsapp_")


class MarketMessageBatchIngest(BaseModel):
    """Batch of up to 50 ingest payloads."""
    items: list[MarketMessageIngest] = Field(min_length=1, max_length=50)


class MarketMessageBatchResult(BaseModel):
    """Per-item result from batch ingestion."""
    dedup_hash: str
    status: str  # "created" | "duplicate" | "error"
    message_id: uuid.UUID | None = None
    detail: str | None = None


# --------------------------------------------------------------------------- #
# Products (DSD §3.2, §5)
# --------------------------------------------------------------------------- #


class ProductCreateRequest(BaseModel):
    brand: str = Field(min_length=1, max_length=100)
    family: str | None = Field(default=None, max_length=100)
    canonical_name: str = Field(min_length=1, max_length=200)
    tier: str = Field(default="unknown", max_length=16)
    is_active: bool = True


class ProductUpdateRequest(BaseModel):
    brand: str | None = Field(default=None, max_length=100)
    family: str | None = Field(default=None, max_length=100)
    canonical_name: str | None = Field(default=None, max_length=200)
    tier: str | None = Field(default=None, max_length=16)
    is_active: bool | None = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brand: str
    family: str | None
    canonical_name: str
    tier: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    alias: str
    source: str


class ProductWithAliasesResponse(ProductResponse):
    aliases: list[ProductAliasResponse] = []


# --------------------------------------------------------------------------- #
# Market messages (DSD §3.1, §6)
# --------------------------------------------------------------------------- #


class MarketMessageProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str = ""
    qty: int | None = None
    unit_price: Decimal | None = None
    currency: str | None = None
    spec: str | None = None
    condition: str | None = None
    grade: str | None = None
    color: str | None = None
    attributes: dict | None = None
    confidence: float
    resolver: str


class MarketMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    source_id: str | None
    sender_raw: str | None
    contact_id: uuid.UUID | None
    contact_name: str | None = None
    side: str
    raw_text: str
    normalized_text: str
    captured_at: datetime
    expires_at: datetime
    status: str
    review_status: str = "AUTO"
    products: list[MarketMessageProductOut] = []
    seen_count: int = 1
    source_groups: list[dict] = []
    created_at: datetime


class MarketMessageListResponse(BaseModel):
    items: list[MarketMessageResponse]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- #
# Search (DSD §6)
# --------------------------------------------------------------------------- #


class MarketSearchParams(BaseModel):
    """Query-time search parameters — deterministic only (R6.1)."""
    q: str = Field(default="", description="Free-text search query")
    side: str | None = Field(default=None, description="BUY | SELL")
    product_ids: list[uuid.UUID] | None = None
    brand: str | None = None
    family: str | None = None
    condition: str | None = None
    grade: str | None = None
    cursor: str | None = Field(default=None, description="Keyset pagination cursor")
    page_size: int = Field(default=50, ge=1, le=200)


class MarketSearchCard(BaseModel):
    """A single result card in the search pane (DSD §6.4-6.5)."""
    market_message_id: uuid.UUID
    contact_id: uuid.UUID | None
    contact_name: str | None
    sender_raw: str | None
    raw_text: str
    side: str
    captured_at: datetime
    freshness_minutes: int
    products: list[MarketMessageProductOut] = []
    seen_count: int = 1
    source_groups: list[dict] = []


class MarketSearchResponse(BaseModel):
    buy_items: list[MarketSearchCard]
    sell_items: list[MarketSearchCard]
    buy_total: int
    sell_total: int
    query_text: str
    resolved_products: list[ProductResponse] = []
    next_cursor: str | None = None
    has_more: bool = False


# --------------------------------------------------------------------------- #
# Saved searches (DSD §7)
# --------------------------------------------------------------------------- #


class SavedSearchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query_text: str = Field(min_length=1)
    resolved_product_ids: list[uuid.UUID] | None = None
    filters: dict | None = None


class SavedSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    query_text: str
    resolved_product_ids: list[uuid.UUID] | None
    filters: dict | None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Search events (DSD §7)
# --------------------------------------------------------------------------- #


class SearchEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    query_text: str
    resolved_product_ids: list[uuid.UUID] | None
    filters: dict | None
    buy_result_count: int
    sell_result_count: int
    executed_at: datetime


# --------------------------------------------------------------------------- #
# Contact product tags (DSD §3.3)
# --------------------------------------------------------------------------- #


class ContactProductTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contact_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str = ""
    product_brand: str = ""
    side_buy_count: int
    side_sell_count: int
    observation_count: int
    first_seen_at: datetime
    last_seen_at: datetime


# --------------------------------------------------------------------------- #
# Outreach (DSD §8)
# --------------------------------------------------------------------------- #


class OutreachSendRequest(BaseModel):
    search_event_id: uuid.UUID | None = None
    contact_id: uuid.UUID
    market_message_id: uuid.UUID | None = None
    template_id: uuid.UUID


class OutreachBatchRequest(BaseModel):
    search_event_id: uuid.UUID | None = None
    sends: list[OutreachSendRequest] = Field(min_length=1, max_length=100)


class OutreachSendResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    search_event_id: uuid.UUID | None
    contact_id: uuid.UUID
    market_message_id: uuid.UUID | None
    template_id: uuid.UUID | None
    template_name: str | None = None
    rendered_body: str | None = None
    status: str
    sent_at: datetime | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Deals (DSD §3.5, §7.3)
# --------------------------------------------------------------------------- #


class DealCreateRequest(BaseModel):
    buyer_contact_id: uuid.UUID | None = None
    seller_contact_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    qty: int | None = None
    target_price: Decimal | None = Field(default=None, max_digits=19, decimal_places=4)
    origin_search_event_id: uuid.UUID | None = None


class DealUpdateRequest(BaseModel):
    status: str | None = None
    qty: int | None = None
    target_price: Decimal | None = Field(default=None, max_digits=19, decimal_places=4)


class DealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    buyer_contact_id: uuid.UUID | None
    seller_contact_id: uuid.UUID | None
    product_id: uuid.UUID | None
    product_name: str | None = None
    qty: int | None
    target_price: Decimal | None
    status: str
    origin_search_event_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Training export (DSD §7.4)
# --------------------------------------------------------------------------- #


class TrainingExportRecord(BaseModel):
    search_event_id: uuid.UUID
    user_id: uuid.UUID | None
    executed_at: datetime
    query_text: str
    resolved_products: list[str] = []
    surfaced_buy: list[dict] = []
    surfaced_sell: list[dict] = []
    selected_contacts: list[uuid.UUID] = []
    templates_sent: list[str] = []
    deals: list[dict] = []
    timings: dict = {}


# --------------------------------------------------------------------------- #
# Archive (P3 — raw message archive endpoint)
# --------------------------------------------------------------------------- #


class MarketArchiveRecord(BaseModel):
    """A single raw message for archive insertion."""
    group_name: str | None = Field(default=None, max_length=255)
    sender_name: str | None = Field(default=None, max_length=255)
    sender_number: str = Field(min_length=1, max_length=64)
    message_timestamp: datetime
    message_content: str = Field(min_length=1)
    msg_type: str | None = Field(default=None, max_length=16)
    tags: list | dict | None = None
    source_msg_id: str = Field(min_length=1, max_length=256)
    status: str = Field(default="lead", pattern=r"^(lead|noise|unreviewed)$")


class MarketArchiveBatchRequest(BaseModel):
    """Batch of archive records (≤500 per batch)."""
    items: list[MarketArchiveRecord] = Field(min_length=1, max_length=500)


class MarketArchiveBatchResult(BaseModel):
    received: int
    inserted: int
    duplicates: int


# --------------------------------------------------------------------------- #
# Review queue (Phase 5)
# --------------------------------------------------------------------------- #


class ResolutionFix(BaseModel):
    """Per-product correction: remap product_id and/or override attributes."""
    product_id: uuid.UUID
    attributes: dict | None = None
    """Optional overrides for {qty, unit_price, currency, color, condition,
    grade, spec}. Keys that match MMP columns are written as column values;
    unknown keys land in the JSONB ``attributes`` column."""


class TeachEntry(BaseModel):
    """Teach the system a new alias → canonical mapping."""
    kind: str = Field(min_length=1, max_length=32)
    alias: str = Field(min_length=1, max_length=200)
    canonical: str = Field(min_length=1, max_length=200)


class ResolveRequest(BaseModel):
    """POST /market/review/{message_id}/resolve payload."""
    corrected_side: str | None = Field(default=None, max_length=8)
    resolutions: list[ResolutionFix] = []
    teach: list[TeachEntry] = []


class ReviewStats(BaseModel):
    """GET /market/review/stats response."""
    queue_depth: int
    inflow_7d: int
    outflow_7d: int
    median_review_seconds: float | None
    capacity_estimate: float | None


class MarketReviewItem(MarketMessageResponse):
    """A single item in the review queue — extends the message response with
    review status and per-field confidence."""
    review_status: str
    field_confidences: dict = {}
    """Per-product-id → per-field confidence map extracted from MMP
    attributes._confidence."""


class ReviewQueueResponse(BaseModel):
    """Cursor-paginated response for GET /market/review."""
    items: list[MarketReviewItem]
    next_cursor: str | None
    """Base64-encoded cursor for the next page, or None if exhausted."""


# --------------------------------------------------------------------------- #
# Attribute vocabulary (Phase 7)
# --------------------------------------------------------------------------- #


class AttributeVocabCreate(BaseModel):
    category: str
    kind: str  # 'closed' | 'open'
    tag: str
    canonical: str
    aliases: list[str] = []
    is_active: bool = True


class AttributeVocabUpdate(BaseModel):
    canonical: str | None = None
    aliases: list[str] | None = None
    is_active: bool | None = None


class AttributeVocabResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category: str
    kind: str
    tag: str
    canonical: str
    aliases: list
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Contact intelligence (Phase 12)
# --------------------------------------------------------------------------- #


class AttributePreferenceItem(BaseModel):
    value: str
    count: int


class AttributePreferences(BaseModel):
    storage: list[AttributePreferenceItem]
    ram: list[AttributePreferenceItem]
    color: list[AttributePreferenceItem]
    region: list[AttributePreferenceItem]
    condition: list[AttributePreferenceItem]


class PriceRangeOut(BaseModel):
    min_unit_price: float | None
    max_unit_price: float | None
    currency: str | None


class ProductInterestOut(BaseModel):
    product_id: str
    product_name: str
    brand: str
    family: str | None
    buy_count: int
    sell_count: int
    observation_count: int
    first_seen: datetime | None
    last_seen: datetime | None


class ContactIntelligenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contact_id: str
    contact_name: str | None
    total_messages: int
    buy_messages: int
    sell_messages: int
    active_since: datetime | None
    last_active: datetime | None
    products: list[ProductInterestOut]
    attribute_preferences: AttributePreferences
    price_range: PriceRangeOut


class ContactsRankedResponse(BaseModel):
    contact_id: str
    contact_name: str | None
    message_count: int
    buy_count: int
    sell_count: int
    top_products: list[str]
