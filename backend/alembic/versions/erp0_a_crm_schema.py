"""ERP-0 Revision A — placeholder (schema separation deferred).

All ERP tables live in the public schema alongside CRM tables. Schema
separation (crm/erp_fin/erp_inv) is deferred to a standalone release
once cross-schema FK resolution is fully understood and tested.
"""

from __future__ import annotations

from alembic import op

revision = "erp0_a_crm_schema"
down_revision = "027_analytics_token_meta_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
