"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-05 00:00:00.000000

Fixes applied in this migration vs original draft:
  DB-C1  — refresh_tokens table added (was missing entirely)
  DB-C2  — ck_conversations_lock_invariant CHECK added:
           (locked_by IS NULL) = (lock_expires_at IS NULL)
  DB-I2  — indexes declared ONLY at migration level; model-level index=True
           removed to prevent double-declaration noise in autogenerate
  DB-I3  — ix_campaigns_created_by added (was missing, caused seq scan)
  DB-I4  — ix_audit_logs_action standalone index added (was composite-only)
  DB-I5  — app_settings key uniqueness via UniqueConstraint, not Index(unique=True)
  DB-M10 — tag seed uses ON CONFLICT DO NOTHING — safe to re-run on partial DB
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------ users
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'agent'"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("role IN ('admin', 'agent')", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # --------------------------------------------------------- refresh_tokens
    # DB-C1 fix: this table was entirely absent from the original migration,
    # causing RefreshTokenRepository to fail at runtime on every auth call.
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        # String(64) is correct for hex-encoded SHA-256 (32 bytes → 64 hex chars).
        # If the hash format ever changes this column must be widened via migration.
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_refresh_tokens_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_refresh_tokens_token_hash",
        "refresh_tokens",
        ["token_hash"],
        unique=True,
    )
    # Index name uses "revoked" (the actual column), not "active".
    op.create_index(
        "ix_refresh_tokens_user_revoked",
        "refresh_tokens",
        ["user_id", "revoked"],
    )
    op.create_index(
        "ix_refresh_tokens_expires_at",
        "refresh_tokens",
        ["expires_at"],
    )

    # ---------------------------------------------------------------- contacts
    op.create_table(
        "contacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column(
            "buyer_seller_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "assigned_agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "revenue_attributed",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("estimated_ltv", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "last_interaction_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "conversation_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_agent_id"],
            ["users.id"],
            name="fk_contacts_assigned_agent_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "buyer_seller_type IN ('buyer', 'seller', 'both', 'unknown')",
            name="ck_contacts_buyer_seller_type",
        ),
    )
    op.create_index("ix_contacts_phone", "contacts", ["phone"], unique=True)
    op.create_index(
        "ix_contacts_assigned_agent_id", "contacts", ["assigned_agent_id"]
    )
    op.create_index(
        "ix_contacts_last_interaction_at",
        "contacts",
        ["last_interaction_at"],
    )

    # ------------------------------------------------------------ conversations
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contact_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "state",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'new'"),
        ),
        sa.Column(
            "ai_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("locked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "lock_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_message_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="fk_conversations_contact_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["locked_by"],
            ["users.id"],
            name="fk_conversations_locked_by",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "state IN ("
            "'new', 'ai_active', 'awaiting_approval', "
            "'human_assigned', 'ai_paused', 'closed'"
            ")",
            name="ck_conversations_state",
        ),
        # DB-C2 fix: database-level enforcement of the lock pairing invariant.
        # locked_by IS NULL iff lock_expires_at IS NULL.
        # Without this, acquire_lock could set locked_by without lock_expires_at
        # (or vice-versa), creating an undefeatable lock with no expiry branch.
        sa.CheckConstraint(
            "(locked_by IS NULL) = (lock_expires_at IS NULL)",
            name="ck_conversations_lock_invariant",
        ),
    )
    op.create_index(
        "ix_conversations_contact_id", "conversations", ["contact_id"]
    )
    op.create_index("ix_conversations_state", "conversations", ["state"])
    op.create_index(
        "ix_conversations_last_message_at",
        "conversations",
        ["last_message_at"],
    )

    # ---------------------------------------------------------------- messages
    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("sender_type", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("meta_message_id", sa.String(255), nullable=True),
        sa.Column(
            "delivery_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("cost", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_messages_direction",
        ),
        sa.CheckConstraint(
            "sender_type IN ('contact', 'agent', 'ai', 'system')",
            name="ck_messages_sender_type",
        ),
        sa.CheckConstraint(
            "delivery_status IN ('queued', 'sent', 'delivered', 'read', 'failed')",
            name="ck_messages_delivery_status",
        ),
    )
    op.create_index(
        "ix_messages_conversation_id", "messages", ["conversation_id"]
    )
    # Partial unique index: only enforce uniqueness when meta_message_id is set.
    op.create_index(
        "ix_messages_meta_message_id",
        "messages",
        ["meta_message_id"],
        unique=True,
        postgresql_where=sa.text("meta_message_id IS NOT NULL"),
    )
    op.create_index(
        "ix_messages_delivery_status", "messages", ["delivery_status"]
    )
    op.create_index("ix_messages_created_at", "messages", ["created_at"])

    # -------------------------------------------------------------------- tags
    op.create_table(
        "tags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    # ------------------------------------------------------------- contact_tags
    op.create_table(
        "contact_tags",
        sa.Column(
            "contact_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "approved_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="fk_contact_tags_contact_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name="fk_contact_tags_tag_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name="fk_contact_tags_approved_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "contact_id", "tag_id", name="pk_contact_tags"
        ),
    )

    # ---------------------------------------------------------- tag_suggestions
    op.create_table(
        "tag_suggestions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contact_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "reviewed_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "reviewed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="fk_tag_suggestions_contact_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tags.id"],
            name="fk_tag_suggestions_tag_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name="fk_tag_suggestions_reviewed_by",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_tag_suggestions_status",
        ),
    )
    op.create_index(
        "ix_tag_suggestions_contact_id", "tag_suggestions", ["contact_id"]
    )
    op.create_index(
        "ix_tag_suggestions_status", "tag_suggestions", ["status"]
    )

    # --------------------------------------------------------------- templates
    op.create_table(
        "templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("meta_template_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column(
            "language",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'en'"),
        ),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_templates_status",
        ),
    )
    op.create_index("ix_templates_name", "templates", ["name"])
    op.create_index("ix_templates_status", "templates", ["status"])

    # --------------------------------------------------------------- campaigns
    op.create_table(
        "campaigns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "campaign_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'immediate'"),
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "audience_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name="fk_campaigns_template_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_campaigns_created_by",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'validating', 'scheduled', 'running', 'completed', 'failed')",
            name="ck_campaigns_status",
        ),
        sa.CheckConstraint(
            "campaign_type IN ('immediate', 'scheduled', 'recurring')",
            name="ck_campaigns_campaign_type",
        ),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])
    # DB-I3 fix: "my campaigns" query was a full seq scan without this index.
    op.create_index("ix_campaigns_created_by", "campaigns", ["created_by"])
    op.create_index(
        "ix_campaigns_scheduled_at", "campaigns", ["scheduled_at"]
    )

    # -------------------------------------------------------- campaign_recipients
    op.create_table(
        "campaign_recipients",
        sa.Column(
            "campaign_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "contact_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "responded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_campaign_recipients_campaign_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="fk_campaign_recipients_contact_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "campaign_id", "contact_id", name="pk_campaign_recipients"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'delivered', 'failed')",
            name="ck_campaign_recipients_status",
        ),
    )
    op.create_index(
        "ix_campaign_recipients_campaign_status",
        "campaign_recipients",
        ["campaign_id", "status"],
    )

    # ---------------------------------------------------------------- ai_events
    op.create_table(
        "ai_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("request", postgresql.JSONB(), nullable=True),
        sa.Column("response", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_ai_events_conversation_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_ai_events_conversation_id", "ai_events", ["conversation_id"]
    )
    op.create_index("ix_ai_events_created_at", "ai_events", ["created_at"])

    # -------------------------------------------------------------- audit_logs
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # DB-I4 fix: standalone action index was absent; only the composite existed.
    # Both are needed: standalone for `WHERE action = ?` lookups,
    # composite for `WHERE action = ? ORDER BY created_at` range scans.
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index(
        "ix_audit_logs_action_created", "audit_logs", ["action", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_entity",
        "audit_logs",
        ["entity_type", "entity_id"],
    )
    op.create_index(
        "ix_audit_logs_actor",
        "audit_logs",
        ["actor_type", "actor_id"],
    )

    # ------------------------------------------------------------ app_settings
    op.create_table(
        "app_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # DB-I5 fix: use explicit UniqueConstraint rather than Index(unique=True).
        # Consistent with the rest of the schema; autogenerate treats them
        # differently and Index(unique=True) produces noisy diffs.
        sa.UniqueConstraint("key", name="uq_app_settings_key"),
    )

    # ---------------------------------------------------- seed default taxonomy
    _seed_tags()


def _seed_tags() -> None:
    """
    Insert the 20 predefined taxonomy tags.

    DB-M10 fix: uses ON CONFLICT DO NOTHING so this is safe to re-run
    on a partially-seeded database without raising UniqueViolation.
    """
    default_tags = [
        ("Buyer", "Contact is a buyer"),
        ("Seller", "Contact is a seller"),
        ("iPhone Buyer", "Interested in iPhone products"),
        ("Samsung Buyer", "Interested in Samsung products"),
        ("Bulk Buyer", "Purchases in bulk quantities"),
        ("Warm Lead", "Engaged lead with moderate interest"),
        ("High Intent", "Strong purchase signal detected"),
        ("Price Sensitive", "Decision highly influenced by price"),
        ("Repeat Customer", "Has purchased previously"),
        ("New Contact", "First interaction with business"),
        ("Unqualified", "Does not meet current qualification criteria"),
        ("Do Not Contact", "Opted out or flagged — do not message"),
        ("VIP", "High-value strategic account"),
        ("Accessories Buyer", "Interested in accessories"),
        ("Wholesaler", "Operates as a wholesale distributor"),
        ("Retailer", "Operates as a retail business"),
        ("Refurbished Interest", "Interested in refurbished stock"),
        ("Follow Up", "Requires scheduled follow-up action"),
        ("Negotiating", "Active price negotiation in progress"),
        ("Closed Won", "Deal successfully closed"),
        ("Inbound Contact", "Contact originated from an inbound message"),
    ]
    for name, description in default_tags:
        op.execute(
            sa.text(
                "INSERT INTO tags (id, name, description) "
                "VALUES (gen_random_uuid(), :name, :description) "
                "ON CONFLICT (name) DO NOTHING"
            ).bindparams(name=name, description=description)
        )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("audit_logs")
    op.drop_table("ai_events")
    op.drop_table("campaign_recipients")
    op.drop_table("campaigns")
    op.drop_table("templates")
    op.drop_table("tag_suggestions")
    op.drop_table("contact_tags")
    op.drop_table("tags")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("contacts")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    # pgcrypto extension is intentionally NOT dropped here.
    # It may be shared with other schemas or system functions.
    # Drop manually via: DROP EXTENSION pgcrypto; if required.
