"""Align templates CHECK constraints with the model enums.

The initial schema (0001) created `ck_templates_status` allowing only
('pending', 'approved', 'rejected') and no category check. The Template
model declares `enum_check` constraints named `ck_templates_status_valid`
(which also permits 'disabled') and `ck_templates_category_valid`.

The 'disabled' status is produced by `map_meta_status` for any Meta state
outside APPROVED/PENDING/REJECTED — now reachable via import-from-Meta and
on-demand sync. Without this migration such a write violates the stale
constraint.

This migration drops the old status constraint and adds both model-aligned
constraints. The `body` column itself already exists (created in 0001), so
no column DDL is needed.
"""
from __future__ import annotations

from alembic import op

revision = "012_template_status_constraints"
down_revision = "011_campaign_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_templates_status", "templates", type_="check")
    op.create_check_constraint(
        "ck_templates_status_valid",
        "templates",
        "status IN ('pending', 'approved', 'rejected', 'disabled')",
    )
    op.create_check_constraint(
        "ck_templates_category_valid",
        "templates",
        "category IN ('marketing', 'utility', 'authentication')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_templates_category_valid", "templates", type_="check")
    op.drop_constraint("ck_templates_status_valid", "templates", type_="check")
    op.create_check_constraint(
        "ck_templates_status",
        "templates",
        "status IN ('pending', 'approved', 'rejected')",
    )
