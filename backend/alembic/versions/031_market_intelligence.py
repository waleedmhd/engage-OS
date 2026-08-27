"""Market intelligence — lead capture, classification, search, outreach, deals (DSD §3).

Creates 9 tables under the ``crm`` schema plus Apple/Samsung product seed data.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime as _dt
from datetime import timezone as _tz

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "031_market_intelligence"
down_revision = "030_add_contact_information"
branch_labels = None
depends_on = None

# Canonical seed product names — prefixed by brand for cross-referencing.
_SEED_PRODUCTS: list[dict] = [
    # Apple
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 17 pro max", "tier": "pro max", "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 17 pro",      "tier": "pro",     "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 17",           "tier": "base",    "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 16 pro max",   "tier": "pro max", "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 16 pro",       "tier": "pro",     "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 16 plus",      "tier": "plus",    "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 16",           "tier": "base",    "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 15 pro max",   "tier": "pro max", "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 15 pro",       "tier": "pro",     "is_active": True},
    {"brand": "Apple", "family": "iPhone", "canonical_name": "iphone 15",           "tier": "base",    "is_active": True},
    # Samsung
    {"brand": "Samsung", "family": "Galaxy S", "canonical_name": "samsung s25 ultra", "tier": "ultra", "is_active": True},
    {"brand": "Samsung", "family": "Galaxy S", "canonical_name": "samsung s25",       "tier": "base",  "is_active": True},
    {"brand": "Samsung", "family": "Galaxy S", "canonical_name": "samsung s24 ultra", "tier": "ultra", "is_active": True},
    {"brand": "Samsung", "family": "Galaxy S", "canonical_name": "samsung s24",       "tier": "base",  "is_active": True},
    {"brand": "Samsung", "family": "Galaxy Z", "canonical_name": "samsung z fold 6",  "tier": "ultra", "is_active": True},
    {"brand": "Samsung", "family": "Galaxy Z", "canonical_name": "samsung z flip 6",  "tier": "pro",   "is_active": True},
]

_SEED_ALIASES: list[dict] = [
    # iPhone 17
    {"canonical_name": "iphone 17 pro max", "alias": "17pm",           "source": "seed"},
    {"canonical_name": "iphone 17 pro max", "alias": "17 pro max",     "source": "seed"},
    {"canonical_name": "iphone 17 pro",     "alias": "17p",            "source": "seed"},
    {"canonical_name": "iphone 17 pro",     "alias": "17 pro",         "source": "seed"},
    {"canonical_name": "iphone 17",         "alias": "i17",            "source": "seed"},
    # iPhone 16
    {"canonical_name": "iphone 16 pro max", "alias": "16pm",           "source": "seed"},
    {"canonical_name": "iphone 16 pro max", "alias": "16 pro max",     "source": "seed"},
    {"canonical_name": "iphone 16 pro max", "alias": "i16pm",          "source": "seed"},
    {"canonical_name": "iphone 16 pro",     "alias": "16p",            "source": "seed"},
    {"canonical_name": "iphone 16 pro",     "alias": "16 pro",         "source": "seed"},
    {"canonical_name": "iphone 16 pro",     "alias": "i16p",           "source": "seed"},
    {"canonical_name": "iphone 16 plus",    "alias": "16 plus",        "source": "seed"},
    {"canonical_name": "iphone 16",         "alias": "i16",            "source": "seed"},
    {"canonical_name": "iphone 16",         "alias": "iph16",          "source": "seed"},
    # iPhone 15
    {"canonical_name": "iphone 15 pro max", "alias": "15pm",           "source": "seed"},
    {"canonical_name": "iphone 15 pro max", "alias": "15 pro max",     "source": "seed"},
    {"canonical_name": "iphone 15 pro",     "alias": "15p",            "source": "seed"},
    {"canonical_name": "iphone 15 pro",     "alias": "15 pro",         "source": "seed"},
    {"canonical_name": "iphone 15",         "alias": "i15",            "source": "seed"},
    # Samsung S25
    {"canonical_name": "samsung s25 ultra", "alias": "s25u",           "source": "seed"},
    {"canonical_name": "samsung s25 ultra", "alias": "s25 ultra",      "source": "seed"},
    {"canonical_name": "samsung s25",       "alias": "s25",            "source": "seed"},
    # Samsung S24
    {"canonical_name": "samsung s24 ultra", "alias": "s24u",           "source": "seed"},
    {"canonical_name": "samsung s24 ultra", "alias": "s24 ultra",      "source": "seed"},
    {"canonical_name": "samsung s24",       "alias": "s24",            "source": "seed"},
    # Samsung Z
    {"canonical_name": "samsung z fold 6",  "alias": "zfold6",         "source": "seed"},
    {"canonical_name": "samsung z fold 6",  "alias": "fold 6",         "source": "seed"},
    {"canonical_name": "samsung z flip 6",  "alias": "zflip6",         "source": "seed"},
    {"canonical_name": "samsung z flip 6",  "alias": "flip 6",         "source": "seed"},
    # Brand-level misspellings
    {"canonical_name": "iphone 16 pro max", "alias": "iphone16 promax","source": "seed"},
    {"canonical_name": "iphone 16 pro",     "alias": "iphone16 pro",   "source": "seed"},
    {"canonical_name": "samsung s25 ultra", "alias": "sam s25u",       "source": "seed"},
    {"canonical_name": "samsung s25",       "alias": "samsng s25",     "source": "seed"},
    {"canonical_name": "samsung s24 ultra", "alias": "sams s24u",      "source": "seed"},
]

_SQL_MARKET_MESSAGE_TRIGRAM = (
    "CREATE INDEX IF NOT EXISTS ix_market_messages_normalized_trgm "
    "ON market_messages USING gin (normalized_text gin_trgm_ops)"
)
_SQL_PRODUCT_ALIAS_TRIGRAM = (
    "CREATE INDEX IF NOT EXISTS ix_product_aliases_alias_trgm "
    "ON product_aliases USING gin (alias gin_trgm_ops)"
)


def upgrade() -> None:
    # pg_trgm extension for fuzzy text search (DSD §6.2).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # --------------------------------------------------------- market_messages
    op.create_table(
        "market_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.String(16), nullable=False, index=True),
        sa.Column("source_id", sa.String(128), nullable=True),
        sa.Column("sender_raw", sa.String(64), nullable=True, index=True),
        sa.Column("contact_id", UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("side", sa.String(8), nullable=False, index=True,
                  server_default="UNKNOWN"),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()"), index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True,
                  server_default="ACTIVE"),
        sa.Column("dedup_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "source_type IN ('group', 'channel', 'dm')",
            name="ck_market_messages_source_type_valid",
        ),
        sa.CheckConstraint(
            "side IN ('BUY', 'SELL', 'UNKNOWN')",
            name="ck_market_messages_side_valid",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUPERSEDED', 'EXPIRED')",
            name="ck_market_messages_status_valid",
        ),
    )
    op.create_index(
        "ix_market_messages_status_side_captured",
        "market_messages", ["status", "side", "captured_at"],
    )
    op.create_index(
        "ix_market_messages_contact_id", "market_messages", ["contact_id"],
    )
    op.create_index(
        "ix_market_messages_expires_at", "market_messages", ["expires_at"],
    )
    op.execute(_SQL_MARKET_MESSAGE_TRIGRAM)

    # ---------------------------------------------------------------- products
    op.create_table(
        "products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("brand", sa.String(100), nullable=False, index=True),
        sa.Column("family", sa.String(100), nullable=True),
        sa.Column("canonical_name", sa.String(200), nullable=False, unique=True, index=True),
        sa.Column("tier", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "tier IN ('base', 'plus', 'pro', 'pro max', 'ultra', 'unknown')",
            name="ck_products_tier_valid",
        ),
    )
    op.create_index("ix_products_brand_family", "products", ["brand", "family"])

    # ---------------------------------------------------------- product_aliases
    op.create_table(
        "product_aliases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("product_id", UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("alias", sa.String(200), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="seed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("product_id", "alias", name="uq_product_aliases_product_alias"),
        sa.CheckConstraint(
            "source IN ('seed', 'llm_learned')",
            name="ck_product_aliases_source_valid",
        ),
    )
    op.create_index("ix_product_aliases_alias", "product_aliases", ["alias"])
    op.execute(_SQL_PRODUCT_ALIAS_TRIGRAM)

    # --------------------------------------------------- market_message_products
    op.create_table(
        "market_message_products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("market_message_id", UUID(as_uuid=True),
                  sa.ForeignKey("market_messages.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("product_id", UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("qty", sa.Integer(), nullable=True),
        sa.Column("unit_price", sa.Numeric(19, 4), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("spec", sa.String(64), nullable=True),
        sa.Column("condition", sa.String(32), nullable=True),
        sa.Column("grade", sa.String(8), nullable=True),
        sa.Column("color", sa.String(32), nullable=True),
        sa.Column("attributes", JSONB(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0"),
        sa.Column("resolver", sa.String(16), nullable=False, server_default="keyword"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "market_message_id", "product_id", name="uq_mmp_message_product",
        ),
        sa.CheckConstraint(
            "resolver IN ('keyword', 'llm')",
            name="ck_market_message_products_resolver_valid",
        ),
    )
    op.create_index("ix_mmp_message_id", "market_message_products", ["market_message_id"])
    op.create_index("ix_mmp_product_id", "market_message_products", ["product_id"])

    # ------------------------------------------------------- contact_product_tags
    op.create_table(
        "contact_product_tags",
        sa.Column("contact_id", UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("side_buy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("side_sell_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()"), index=True),
        sa.PrimaryKeyConstraint("contact_id", "product_id", name="pk_contact_product_tags"),
    )
    op.create_index(
        "ix_contact_product_tags_product_id", "contact_product_tags", ["product_id"],
    )
    op.create_index(
        "ix_contact_product_tags_last_seen", "contact_product_tags", ["last_seen_at"],
    )

    # ------------------------------------------------------------ saved_searches
    op.create_table(
        "saved_searches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("resolved_product_ids", JSONB(), nullable=True),
        sa.Column("filters", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # ------------------------------------------------------------- search_events
    op.create_table(
        "search_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("resolved_product_ids", JSONB(), nullable=True),
        sa.Column("filters", JSONB(), nullable=True),
        sa.Column("buy_result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sell_result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_search_events_user_executed", "search_events", ["user_id", "executed_at"],
    )

    # ----------------------------------------------------------- outreach_sends
    op.create_table(
        "outreach_sends",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("search_event_id", UUID(as_uuid=True),
                  sa.ForeignKey("search_events.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("contact_id", UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("market_message_id", UUID(as_uuid=True),
                  sa.ForeignKey("market_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("template_id", UUID(as_uuid=True),
                  sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rendered_body", sa.Text(), nullable=True),
        sa.Column("sent_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_message_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, index=True,
                  server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'delivered', 'failed')",
            name="ck_outreach_sends_status_valid",
        ),
    )
    op.create_index("ix_outreach_sends_search_event", "outreach_sends", ["search_event_id"])
    op.create_index("ix_outreach_sends_contact", "outreach_sends", ["contact_id"])

    # -------------------------------------------------------------------- deals
    op.create_table(
        "deals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("buyer_contact_id", UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("seller_contact_id", UUID(as_uuid=True),
                  sa.ForeignKey("contacts.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("product_id", UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("qty", sa.Integer(), nullable=True),
        sa.Column("target_price", sa.Numeric(19, 4), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, index=True,
                  server_default="matched"),
        sa.Column("origin_search_event_id", UUID(as_uuid=True),
                  sa.ForeignKey("search_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('matched', 'contacted', 'negotiating', 'confirmed', 'closed', 'lost')",
            name="ck_deals_status_valid",
        ),
    )
    op.create_index("ix_deals_origin_search_event", "deals", ["origin_search_event_id"])

    # --------------------------------------------------------------- seed data
    now = _dt.now(tz=_tz.utc)
    product_rows = [
        {**p, "id": _uuid.uuid4(), "created_at": now, "updated_at": now}
        for p in _SEED_PRODUCTS
    ]
    op.bulk_insert(sa.table(
        "products",
        sa.column("id", UUID),
        sa.column("brand", sa.String),
        sa.column("family", sa.String),
        sa.column("canonical_name", sa.String),
        sa.column("tier", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    ), product_rows)

    # Resolve alias product_id references against the canonical names.
    name_to_id: dict[str, _uuid.UUID] = {
        p["canonical_name"]: p["id"] for p in product_rows
    }
    alias_rows: list[dict] = []
    for a in _SEED_ALIASES:
        pid = name_to_id.get(a["canonical_name"])
        if pid is None:
            continue
        alias_rows.append({
            "id": _uuid.uuid4(),
            "product_id": pid,
            "alias": a["alias"],
            "source": a["source"],
            "created_at": now,
        })
    if alias_rows:
        op.bulk_insert(sa.table(
            "product_aliases",
            sa.column("id", UUID),
            sa.column("product_id", UUID),
            sa.column("alias", sa.String),
            sa.column("source", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ), alias_rows)


def downgrade() -> None:
    op.drop_table("deals")
    op.drop_table("outreach_sends")
    op.drop_table("search_events")
    op.drop_table("saved_searches")
    op.drop_table("contact_product_tags")
    op.drop_table("market_message_products")
    op.drop_table("product_aliases")
    op.drop_table("products")
    op.drop_table("market_messages")
