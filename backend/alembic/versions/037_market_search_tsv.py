"""Phase 11 — Full-text search on market_messages.

Adds a GIN-indexed tsvector column (search_tsv) with a trigger to keep it
in sync on INSERT/UPDATE, weighted: raw_text = A, normalized_text = B.
"""

from __future__ import annotations

from alembic import op

revision = "037_market_search_tsv"
down_revision = "036_extractor_attributes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE market_messages ADD COLUMN search_tsv tsvector")
    op.execute(
        "CREATE INDEX ix_market_messages_search_tsv "
        "ON market_messages USING GIN (search_tsv)"
    )
    op.execute(
        "UPDATE market_messages SET search_tsv = "
        "setweight(to_tsvector('english', coalesce(raw_text, '')), 'A') || "
        "setweight(to_tsvector('english', coalesce(normalized_text, '')), 'B')"
    )
    op.execute(
        "CREATE FUNCTION market_messages_search_tsv_trigger() RETURNS trigger AS $$\n"
        "BEGIN\n"
        "    NEW.search_tsv :=\n"
        "        setweight(to_tsvector('english', coalesce(NEW.raw_text, '')), 'A') ||\n"
        "        setweight(to_tsvector('english', coalesce(NEW.normalized_text, '')), 'B');\n"
        "    RETURN NEW;\n"
        "END;\n"
        "$$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER trg_market_messages_search_tsv\n"
        "    BEFORE INSERT OR UPDATE OF raw_text, normalized_text ON market_messages\n"
        "    FOR EACH ROW EXECUTE FUNCTION market_messages_search_tsv_trigger()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_market_messages_search_tsv ON market_messages"
    )
    op.execute("DROP FUNCTION IF EXISTS market_messages_search_tsv_trigger()")
    op.execute("DROP INDEX IF EXISTS ix_market_messages_search_tsv")
    op.execute("ALTER TABLE market_messages DROP COLUMN IF EXISTS search_tsv")
