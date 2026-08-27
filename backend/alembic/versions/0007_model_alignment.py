"""Model-alignment patch: close all gaps between models and migrations 0001–0006.

Revision ID: 007_model_alignment
Revises: 006_analytics_rollups
Create Date: 2026-05-16 00:00:00.000000

Each change is annotated with the gap it closes:
  MA-1   conversations.state constraint/default is lowercase; model uses uppercase StrEnum
  MA-2   messages.delivery_status constraint missing 'pending'; model default = 'pending'
  MA-3   campaigns.status constraint missing 'queued', 'dispatching', 'cancelled'; has stale 'running'
  MA-4   campaigns.campaign_type column → rename to 'type' (matches model attribute)
  MA-5   campaigns.created_by was NOT NULL/RESTRICT; model is nullable/SET NULL
  MA-6   campaigns missing sent_count, delivered_count, failed_count, response_count columns
  MA-7   contacts missing 'status' column (ContactStatus enum)
  MA-8   campaign_recipients: composite PK → UUID PK; missing id, timestamps, error_message
  MA-9   ai_events missing intent, confidence, error columns + updated_at
  MA-10  app_settings: value is Text (model uses JSONB); missing scope column; wrong unique key
  MA-11  users.full_name column → rename to 'name' (matches model attribute)
  MA-12  refresh_tokens / tags / audit_logs missing updated_at (from TimestampMixin)
  MA-13  tag_suggestions.confidence was NOT NULL; model is nullable
  MA-14  Missing indexes: composite + GIN across multiple tables
  MA-15  Index rename: ix_refresh_tokens_user_revoked → ix_refresh_tokens_user_active
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "007_model_alignment"
down_revision = "006_analytics_rollups"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # =========================================================================
    # MA-1  conversations.state — migrate from lowercase to uppercase values
    # =========================================================================
    # The original constraint allowed lowercase ('new', 'ai_active', …) but
    # ConversationState is a StrEnum with uppercase values ('NEW', 'AI_ACTIVE', …).
    # ORM inserts have been writing uppercase, which would have violated the old
    # constraint. Fix: drop old constraint, uppercase all existing rows, add new
    # constraint with uppercase values, update server_default.

    op.drop_constraint("ck_conversations_state", "conversations", type_="check")
    op.execute(
        sa.text(
            "UPDATE conversations SET state = UPPER(state) "
            "WHERE state != UPPER(state)"
        )
    )
    op.create_check_constraint(
        "ck_conversations_state",
        "conversations",
        "state IN ('NEW', 'AI_ACTIVE', 'AWAITING_APPROVAL', 'HUMAN_ASSIGNED', 'AI_PAUSED', 'CLOSED')",
    )
    op.alter_column(
        "conversations",
        "state",
        server_default=sa.text("'NEW'"),
        type_=sa.String(32),
    )

    # =========================================================================
    # MA-2  messages.delivery_status — add 'pending' to constraint + fix default
    # =========================================================================
    # Migration 0003 added 'draft'; the model added 'pending' as a new status
    # but never added it to the check constraint. The model server_default is
    # 'pending', so any ORM insert without an explicit status would fail.

    op.drop_constraint("ck_messages_delivery_status", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_delivery_status",
        "messages",
        "delivery_status IN ('pending', 'draft', 'queued', 'sent', 'delivered', 'read', 'failed')",
    )
    op.alter_column(
        "messages",
        "delivery_status",
        server_default=sa.text("'pending'"),
    )
    # Widen direction/sender_type to match model (String(16) vs original String(10))
    op.alter_column("messages", "direction", type_=sa.String(16), existing_nullable=False)
    op.alter_column("messages", "sender_type", type_=sa.String(16), existing_nullable=False)

    # =========================================================================
    # MA-3  campaigns.status — fix allowed values
    # =========================================================================
    # Old constraint: 'draft', 'validating', 'scheduled', 'running', 'completed', 'failed'
    # CampaignStatus enum: 'draft', 'validating', 'scheduled', 'queued',
    #                       'dispatching', 'completed', 'failed', 'cancelled'
    # 'running' → nearest equivalent is 'dispatching'; migrate stale rows first.

    op.execute(
        sa.text(
            "UPDATE campaigns SET status = 'dispatching' WHERE status = 'running'"
        )
    )
    op.drop_constraint("ck_campaigns_status", "campaigns", type_="check")
    op.create_check_constraint(
        "ck_campaigns_status",
        "campaigns",
        "status IN ('draft', 'validating', 'scheduled', 'queued', 'dispatching', 'completed', 'failed', 'cancelled')",
    )

    # =========================================================================
    # MA-4  campaigns.campaign_type → rename to 'type'
    # =========================================================================
    # Migration 0001 created the column as 'campaign_type'; the model defines it
    # as `type`. PostgreSQL automatically updates the index ix_campaigns_type_next_run_at
    # (which references this column) when the column is renamed — no manual
    # index rebuild required.

    op.alter_column("campaigns", "campaign_type", new_column_name="type")

    # Also rename the check constraint to match model's naming convention.
    op.drop_constraint("ck_campaigns_campaign_type", "campaigns", type_="check")
    op.create_check_constraint(
        "ck_campaigns_type_valid",
        "campaigns",
        "type IN ('immediate', 'scheduled', 'recurring')",
    )

    # =========================================================================
    # MA-5  campaigns.created_by — nullable + FK ondelete change
    # =========================================================================
    # Model has nullable=True and ondelete="SET NULL"; migration had NOT NULL/RESTRICT.

    op.drop_constraint("fk_campaigns_created_by", "campaigns", type_="foreignkey")
    op.alter_column("campaigns", "created_by", nullable=True, existing_type=postgresql.UUID(as_uuid=True))
    op.create_foreign_key(
        "fk_campaigns_created_by",
        "campaigns",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # =========================================================================
    # MA-6  campaigns — add delivery counter columns
    # =========================================================================

    op.add_column("campaigns", sa.Column("sent_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("campaigns", sa.Column("delivered_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("campaigns", sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("campaigns", sa.Column("response_count", sa.Integer(), nullable=False, server_default=sa.text("0")))

    # =========================================================================
    # MA-7  contacts — add 'status' column
    # =========================================================================

    op.add_column(
        "contacts",
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.create_check_constraint(
        "ck_contacts_status_valid",
        "contacts",
        "status IN ('active', 'inactive', 'blocked')",
    )
    # Widen phone to match model String(32) (was String(20))
    op.alter_column("contacts", "phone", type_=sa.String(32), existing_nullable=False)
    # Widen revenue_attributed / estimated_ltv to Numeric(14, 2) (was Numeric(12, 2))
    op.alter_column("contacts", "revenue_attributed", type_=sa.Numeric(14, 2), existing_nullable=False)
    op.alter_column("contacts", "estimated_ltv", type_=sa.Numeric(14, 2), existing_nullable=True)

    # =========================================================================
    # MA-8  campaign_recipients — UUID PK + timestamps + error_message
    # =========================================================================
    # Original PK was (campaign_id, contact_id). Model uses UUIDPKMixin (id PK)
    # with a unique constraint on (campaign_id, contact_id).
    # Steps:
    #   1. Add id column (nullable so existing rows can populate it)
    #   2. Backfill id for all existing rows
    #   3. Set id NOT NULL
    #   4. Drop composite PK, add UUID PK
    #   5. Add unique constraint replacing the old PK semantics
    #   6. Add timestamp and error_message columns

    op.add_column(
        "campaign_recipients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE campaign_recipients SET id = gen_random_uuid() WHERE id IS NULL"
        )
    )
    op.alter_column("campaign_recipients", "id", nullable=False)
    op.drop_constraint("pk_campaign_recipients", "campaign_recipients", type_="primary")
    op.create_primary_key("pk_campaign_recipients", "campaign_recipients", ["id"])
    op.create_unique_constraint(
        "uq_campaign_recipients_campaign_contact",
        "campaign_recipients",
        ["campaign_id", "contact_id"],
    )

    op.add_column(
        "campaign_recipients",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "campaign_recipients",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "campaign_recipients",
        sa.Column("error_message", sa.String(500), nullable=True),
    )

    # =========================================================================
    # MA-9  ai_events — add intent, confidence, error, updated_at
    # =========================================================================
    # Also fix request/response nullability (model: NOT NULL with server_default={})

    op.add_column("ai_events", sa.Column("intent", sa.String(64), nullable=True))
    op.add_column("ai_events", sa.Column("confidence", sa.Numeric(4, 3), nullable=True))
    op.add_column("ai_events", sa.Column("error", sa.Text(), nullable=True))
    op.add_column(
        "ai_events",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Fix nullability of request/response and add server defaults
    op.execute(sa.text("UPDATE ai_events SET request = '{}' WHERE request IS NULL"))
    op.execute(sa.text("UPDATE ai_events SET response = '{}' WHERE response IS NULL"))
    op.alter_column("ai_events", "request", nullable=False, server_default=sa.text("'{}'::jsonb"))
    op.alter_column("ai_events", "response", nullable=False, server_default=sa.text("'{}'::jsonb"))

    # =========================================================================
    # MA-10  app_settings — add scope, change value to JSONB, update unique key
    # =========================================================================

    # Add scope with a default so existing rows get 'global'
    op.add_column(
        "app_settings",
        sa.Column(
            "scope",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'global'"),
        ),
    )
    # Widen key column
    op.alter_column("app_settings", "key", type_=sa.String(128), existing_nullable=False)
    # Migrate value from Text to JSONB
    # Existing text values should already be valid JSON (the app sets them that way).
    # Rows with NULL value get an empty object.
    op.execute(sa.text("UPDATE app_settings SET value = '{}' WHERE value IS NULL"))
    op.alter_column(
        "app_settings",
        "value",
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using="value::jsonb",
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    # Replace the old per-key unique constraint with a (scope, key) unique index
    op.drop_constraint("uq_app_settings_key", "app_settings", type_="unique")
    op.create_index(
        "ix_app_settings_scope_key",
        "app_settings",
        ["scope", "key"],
        unique=True,
    )

    # =========================================================================
    # MA-11  users.full_name → users.name
    # =========================================================================
    # Model column attribute is 'name'. PostgreSQL auto-updates any dependent
    # indexes/constraints on rename.

    op.alter_column("users", "full_name", new_column_name="name")
    op.alter_column("users", "name", type_=sa.String(200), existing_nullable=True)
    # Widen role column to match model String(32) (was String(20))
    op.alter_column("users", "role", type_=sa.String(32), existing_nullable=False)

    # =========================================================================
    # MA-12  Add missing updated_at to refresh_tokens, tags, audit_logs
    # =========================================================================
    # TimestampMixin declares both created_at and updated_at; migrations only
    # created created_at for these three tables.

    for table in ("refresh_tokens", "tags", "audit_logs"):
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    # =========================================================================
    # MA-13  tag_suggestions.confidence — remove NOT NULL
    # =========================================================================

    op.alter_column("tag_suggestions", "confidence", nullable=True, existing_type=sa.Numeric(4, 3))

    # =========================================================================
    # MA-14  Missing indexes
    # =========================================================================

    # --- users ---
    op.create_index("ix_users_role_active", "users", ["role", "is_active"])

    # --- contacts ---
    op.create_index(
        "ix_contacts_status_last_interaction",
        "contacts",
        ["status", "last_interaction_at"],
    )
    op.create_index(
        "ix_contacts_assigned_agent_status",
        "contacts",
        ["assigned_agent_id", "status"],
    )

    # --- conversations ---
    op.create_index(
        "ix_conversations_state_last_message",
        "conversations",
        ["state", "last_message_at"],
    )
    op.create_index(
        "ix_conversations_contact_state",
        "conversations",
        ["contact_id", "state"],
    )

    # --- messages ---
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_messages_delivery_status_created",
        "messages",
        ["delivery_status", "created_at"],
    )

    # --- campaigns ---
    op.create_index(
        "ix_campaigns_status_scheduled_at",
        "campaigns",
        ["status", "scheduled_at"],
    )

    # --- ai_events ---
    op.create_index(
        "ix_ai_events_conversation_created",
        "ai_events",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_ai_events_request_gin",
        "ai_events",
        ["request"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_ai_events_response_gin",
        "ai_events",
        ["response"],
        postgresql_using="gin",
    )

    # --- tag_suggestions ---
    op.create_index(
        "ix_tag_suggestions_status_created_at",
        "tag_suggestions",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_tag_suggestions_contact_status",
        "tag_suggestions",
        ["contact_id", "status"],
    )

    # --- contact_tags ---
    op.create_index("ix_contact_tags_tag_id", "contact_tags", ["tag_id"])

    # --- templates ---
    op.create_index(
        "ix_templates_status_category",
        "templates",
        ["status", "category"],
    )

    # --- audit_logs (GIN for JSONB search) ---
    op.create_index(
        "ix_audit_logs_before_state_gin",
        "audit_logs",
        ["before_state"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_audit_logs_after_state_gin",
        "audit_logs",
        ["after_state"],
        postgresql_using="gin",
    )

    # =========================================================================
    # MA-15  Index rename: ix_refresh_tokens_user_revoked → ix_refresh_tokens_user_active
    # =========================================================================
    # Same columns (user_id, revoked); only the name changed in the model.

    op.drop_index("ix_refresh_tokens_user_revoked", table_name="refresh_tokens")
    op.create_index(
        "ix_refresh_tokens_user_active",
        "refresh_tokens",
        ["user_id", "revoked"],
    )


def downgrade() -> None:
    # =========================================================================
    # Reverse MA-15
    # =========================================================================
    op.drop_index("ix_refresh_tokens_user_active", table_name="refresh_tokens")
    op.create_index(
        "ix_refresh_tokens_user_revoked",
        "refresh_tokens",
        ["user_id", "revoked"],
    )

    # =========================================================================
    # Reverse MA-14 — drop all added indexes
    # =========================================================================
    op.drop_index("ix_audit_logs_after_state_gin", table_name="audit_logs")
    op.drop_index("ix_audit_logs_before_state_gin", table_name="audit_logs")
    op.drop_index("ix_templates_status_category", table_name="templates")
    op.drop_index("ix_contact_tags_tag_id", table_name="contact_tags")
    op.drop_index("ix_tag_suggestions_contact_status", table_name="tag_suggestions")
    op.drop_index("ix_tag_suggestions_status_created_at", table_name="tag_suggestions")
    op.drop_index("ix_ai_events_response_gin", table_name="ai_events")
    op.drop_index("ix_ai_events_request_gin", table_name="ai_events")
    op.drop_index("ix_ai_events_conversation_created", table_name="ai_events")
    op.drop_index("ix_campaigns_status_scheduled_at", table_name="campaigns")
    op.drop_index("ix_messages_delivery_status_created", table_name="messages")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_conversations_contact_state", table_name="conversations")
    op.drop_index("ix_conversations_state_last_message", table_name="conversations")
    op.drop_index("ix_contacts_assigned_agent_status", table_name="contacts")
    op.drop_index("ix_contacts_status_last_interaction", table_name="contacts")
    op.drop_index("ix_users_role_active", table_name="users")

    # =========================================================================
    # Reverse MA-13
    # =========================================================================
    op.alter_column("tag_suggestions", "confidence", nullable=False, existing_type=sa.Numeric(4, 3))

    # =========================================================================
    # Reverse MA-12
    # =========================================================================
    for table in ("refresh_tokens", "tags", "audit_logs"):
        op.drop_column(table, "updated_at")

    # =========================================================================
    # Reverse MA-11
    # =========================================================================
    op.alter_column("users", "role", type_=sa.String(20), existing_nullable=False)
    op.alter_column("users", "name", type_=sa.String(255), existing_nullable=True)
    op.alter_column("users", "name", new_column_name="full_name")

    # =========================================================================
    # Reverse MA-10
    # =========================================================================
    op.drop_index("ix_app_settings_scope_key", table_name="app_settings")
    op.create_unique_constraint("uq_app_settings_key", "app_settings", ["key"])
    op.alter_column(
        "app_settings",
        "value",
        type_=sa.Text(),
        postgresql_using="value::text",
        nullable=True,
        server_default=None,
    )
    op.alter_column("app_settings", "key", type_=sa.String(100), existing_nullable=False)
    op.drop_column("app_settings", "scope")

    # =========================================================================
    # Reverse MA-9
    # =========================================================================
    op.alter_column("ai_events", "request", nullable=True, server_default=None)
    op.alter_column("ai_events", "response", nullable=True, server_default=None)
    op.drop_column("ai_events", "updated_at")
    op.drop_column("ai_events", "error")
    op.drop_column("ai_events", "confidence")
    op.drop_column("ai_events", "intent")

    # =========================================================================
    # Reverse MA-8 — partial: restore composite PK, drop added columns
    # NOTE: This cannot fully reverse if new rows were inserted after the upgrade
    # (they would have no valid campaign_id/contact_id combination to serve as PK).
    # =========================================================================
    op.drop_column("campaign_recipients", "error_message")
    op.drop_column("campaign_recipients", "updated_at")
    op.drop_column("campaign_recipients", "created_at")
    op.drop_constraint("uq_campaign_recipients_campaign_contact", "campaign_recipients", type_="unique")
    op.drop_constraint("pk_campaign_recipients", "campaign_recipients", type_="primary")
    op.create_primary_key("pk_campaign_recipients", "campaign_recipients", ["campaign_id", "contact_id"])
    op.drop_column("campaign_recipients", "id")

    # =========================================================================
    # Reverse MA-7
    # =========================================================================
    op.alter_column("contacts", "estimated_ltv", type_=sa.Numeric(12, 2), existing_nullable=True)
    op.alter_column("contacts", "revenue_attributed", type_=sa.Numeric(12, 2), existing_nullable=False)
    op.alter_column("contacts", "phone", type_=sa.String(20), existing_nullable=False)
    op.drop_constraint("ck_contacts_status_valid", "contacts", type_="check")
    op.drop_column("contacts", "status")

    # =========================================================================
    # Reverse MA-6
    # =========================================================================
    op.drop_column("campaigns", "response_count")
    op.drop_column("campaigns", "failed_count")
    op.drop_column("campaigns", "delivered_count")
    op.drop_column("campaigns", "sent_count")

    # =========================================================================
    # Reverse MA-5
    # =========================================================================
    op.drop_constraint("fk_campaigns_created_by", "campaigns", type_="foreignkey")
    op.alter_column("campaigns", "created_by", nullable=False, existing_type=postgresql.UUID(as_uuid=True))
    op.create_foreign_key(
        "fk_campaigns_created_by",
        "campaigns",
        "users",
        ["created_by"],
        ["id"],
        ondelete="RESTRICT",
    )

    # =========================================================================
    # Reverse MA-4
    # =========================================================================
    op.drop_constraint("ck_campaigns_type_valid", "campaigns", type_="check")
    op.create_check_constraint(
        "ck_campaigns_campaign_type",
        "campaigns",
        "type IN ('immediate', 'scheduled', 'recurring')",
    )
    op.alter_column("campaigns", "type", new_column_name="campaign_type")

    # =========================================================================
    # Reverse MA-3
    # =========================================================================
    op.drop_constraint("ck_campaigns_status", "campaigns", type_="check")
    op.create_check_constraint(
        "ck_campaigns_status",
        "campaigns",
        "status IN ('draft', 'validating', 'scheduled', 'running', 'completed', 'failed')",
    )

    # =========================================================================
    # Reverse MA-2
    # =========================================================================
    op.alter_column("messages", "sender_type", type_=sa.String(10), existing_nullable=False)
    op.alter_column("messages", "direction", type_=sa.String(10), existing_nullable=False)
    op.alter_column("messages", "delivery_status", server_default=sa.text("'queued'"))
    op.drop_constraint("ck_messages_delivery_status", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_delivery_status",
        "messages",
        "delivery_status IN ('draft', 'queued', 'sent', 'delivered', 'read', 'failed')",
    )

    # =========================================================================
    # Reverse MA-1
    # =========================================================================
    op.execute(
        sa.text(
            "UPDATE conversations SET state = LOWER(state) "
            "WHERE state != LOWER(state)"
        )
    )
    op.drop_constraint("ck_conversations_state", "conversations", type_="check")
    op.create_check_constraint(
        "ck_conversations_state",
        "conversations",
        "state IN ('new', 'ai_active', 'awaiting_approval', 'human_assigned', 'ai_paused', 'closed')",
    )
    op.alter_column(
        "conversations",
        "state",
        server_default=sa.text("'new'"),
        type_=sa.String(30),
    )
