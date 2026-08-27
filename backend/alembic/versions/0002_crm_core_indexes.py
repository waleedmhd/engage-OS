"""crm core: pg_trgm + search indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-08 00:00:00.000000

Phase 5 (CRM Core) performance migration.

Adds the pg_trgm extension and GIN trigram indexes on contacts.name,
contacts.phone, and contacts.company. Without these, ILIKE '%foo%'
queries used by `ContactRepository.search` and `list_with_filters(q=...)`
fall back to sequential scan; the inbox `q=` filter on contacts joined
into conversations would be unusable past a few thousand rows.

The composite ordering indexes (status + last_interaction_at;
assigned_agent_id + status; state + last_message_at) are already declared
at the model level via __table_args__ and were created by migration 0001.
"""

from __future__ import annotations

from alembic import op


revision = "002_crm_core_indexes"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contacts_name_trgm "
        "ON contacts USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contacts_phone_trgm "
        "ON contacts USING gin (phone gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contacts_company_trgm "
        "ON contacts USING gin (company gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contacts_company_trgm")
    op.execute("DROP INDEX IF EXISTS ix_contacts_phone_trgm")
    op.execute("DROP INDEX IF EXISTS ix_contacts_name_trgm")
    # NOTE: the pg_trgm extension is intentionally NOT dropped here.
    # Other migrations (e.g. messaging search, future categorization
    # search) may rely on it, and dropping a shared extension during
    # a single-feature downgrade is unsafe.
