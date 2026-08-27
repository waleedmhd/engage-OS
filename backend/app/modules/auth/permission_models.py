"""ERP permission models — extend the auth system with fine-grained grants.

These tables live in the `crm` schema alongside `users`. Admin is an implicit
wildcard (no rows needed). Every other role must have explicit grants.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPKMixin


class ErpPermission(UUIDPKMixin, Base):
    """Permission code registry — seeded with all ERP module.action codes."""

    __tablename__ = "erp_permissions"
    __table_args__: tuple = (
        Index("ix_erp_permissions_module", "module"),
        
    )

    code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    module: Mapped[str] = mapped_column(
        String(50), nullable=False
    )


class UserPermission(Base):
    """Explicit permission grant: (user_id, permission_code).

    No UUIDPK — the natural key is (user_id, permission_code).
    """

    __tablename__ = "user_permissions"
    __table_args__: tuple = (
        Index("ix_user_permissions_user", "user_id"),
        Index("ix_user_permissions_code", "permission_code"),
        
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    permission_code: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("erp_permissions.code", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )


# ------------------------------------------------------- seeded permission codes

PERMISSION_CODES: list[tuple[str, str, str]] = [
    # --- Finance / Ledger ---
    ("erp_fin.journal.post", "Create and post manual journal entries", "ledger"),
    ("erp_fin.journal.reverse", "Reverse posted journal entries", "ledger"),
    ("erp_fin.coa.manage", "Create, edit, and deactivate accounts in the chart of accounts", "ledger"),
    ("erp_fin.period.manage", "Open and close fiscal periods", "ledger"),
    ("erp_fin.period.reopen", "Reopen a closed or locked fiscal period", "ledger"),

    # --- Accounts Receivable ---
    ("erp_ar.invoice.create", "Create sales invoices", "receivables"),
    ("erp_ar.invoice.void", "Void issued invoices", "receivables"),
    ("erp_ar.payment.create", "Record customer payments", "receivables"),
    ("erp_ar.payment.allocate", "Allocate payments to invoices", "receivables"),
    ("erp_ar.credit_note.create", "Issue credit notes", "receivables"),

    # --- Accounts Payable ---
    ("erp_ap.bill.create", "Create supplier bills", "payables"),
    ("erp_ap.bill.void", "Void issued bills", "payables"),
    ("erp_ap.payment.create", "Record supplier payments", "payables"),
    ("erp_ap.payment.allocate", "Allocate payments to bills", "payables"),
    ("erp_ap.debit_note.create", "Issue debit notes", "payables"),

    # --- Inventory ---
    ("erp_inv.item.manage", "Create, edit, and deactivate items", "inventory"),
    ("erp_inv.stock.view", "View stock on hand and serial lookups", "inventory"),
    ("erp_inv.stock.adjust", "Create stock adjustments (write-offs, gains)", "inventory"),
    ("erp_inv.stock.transfer", "Create stock transfers between locations", "inventory"),
    ("erp_inv.stock.count", "Create and confirm stock counts", "inventory"),

    # --- Procurement ---
    ("erp_proc.po.create", "Create purchase orders", "procurement"),
    ("erp_proc.po.approve", "Approve purchase orders", "procurement"),
    ("erp_proc.grn.create", "Create goods receipt notes (GRNs)", "procurement"),

    # --- Fulfilment ---
    ("erp_ful.so.create", "Create sales orders", "fulfilment"),
    ("erp_ful.so.approve", "Approve sales orders", "fulfilment"),
    ("erp_ful.dispatch.create", "Create dispatch / delivery notes", "fulfilment"),

    # --- Reporting ---
    ("erp_rep.statements.view", "View Trial Balance, P&L, Balance Sheet", "erp_reporting"),
    ("erp_rep.ageing.view", "View AR and AP ageing reports", "erp_reporting"),
    ("erp_rep.margin.view", "View margin and profitability reports", "erp_reporting"),
    ("erp_rep.settings.manage", "Manage ERP settings", "erp_reporting"),
]

# ---------------------------------------------------------- section access model


class UserAccessibleSection(Base):
    """Per-user sidebar section visibility grant.

    Admin is an implicit wildcard — no rows needed. Agents get explicit
    grants; if an agent has zero grants they default to CRM-only sections.
    """

    __tablename__ = "user_accessible_sections"
    __table_args__: tuple = (
        Index("ix_user_accessible_sections_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    section_key: Mapped[str] = mapped_column(
        String(100), nullable=False, primary_key=True
    )


# Canonical section keys — each matches a sidebar href without the leading /.
ALL_SECTIONS: list[str] = [
    # CRM
    "inbox",
    "market",
    "market/review",
    "contacts",
    "campaigns",
    "templates",
    "tag-review",
    # Finance & Inventory
    "finance/accounts",
    "finance/journals",
    "finance/receivables",
    "finance/payables",
    "inventory/items",
    "inventory/stock",
    "inventory/procurement",
    "inventory/fulfilment",
    "reports",
    # Admin
    "analytics",
    "settings",
    "settings/tags",
    "settings/campaign-categories",
    "users",
    "audit-logs",
]

DEFAULT_AGENT_SECTIONS: list[str] = [
    "inbox",
    "market",
    "market/review",
    "contacts",
    "campaigns",
    "templates",
    "tag-review",
]

# Named bundles an admin applies to an agent in one action.
PERMISSION_PRESETS: dict[str, list[str]] = {
    "Accountant": [
        "erp_fin.journal.post", "erp_fin.journal.reverse",
        "erp_fin.coa.manage", "erp_fin.period.manage", "erp_fin.period.reopen",
        "erp_rep.statements.view", "erp_rep.ageing.view",
    ],
    "Inventory Clerk": [
        "erp_inv.item.manage", "erp_inv.stock.view",
        "erp_inv.stock.adjust", "erp_inv.stock.transfer", "erp_inv.stock.count",
    ],
    "Sales": [
        "erp_ar.invoice.create", "erp_ar.invoice.void",
        "erp_ar.payment.create", "erp_ar.payment.allocate",
        "erp_ar.credit_note.create", "erp_ful.so.create", "erp_ful.so.approve",
    ],
    "Purchasing": [
        "erp_ap.bill.create", "erp_ap.bill.void",
        "erp_ap.payment.create", "erp_ap.payment.allocate",
        "erp_ap.debit_note.create", "erp_proc.po.create", "erp_proc.po.approve",
        "erp_proc.grn.create",
    ],
    "Auditor": [],  # Read-only — no write permissions needed
}
