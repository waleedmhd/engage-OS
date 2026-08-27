"""Ledger module constants — account types, journal status, period status."""

from enum import StrEnum


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    COGS = "cogs"  # cost of goods sold
    OPEX = "opex"  # operating expenses


class AccountNormalSide(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalStatus(StrEnum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class JournalVoucherType(StrEnum):
    """ERPNext-inspired voucher types — subset relevant to single-company wholesale."""
    JOURNAL_ENTRY = "journal_entry"
    BANK_ENTRY = "bank_entry"
    CASH_ENTRY = "cash_entry"
    CONTRA_ENTRY = "contra_entry"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"
    WRITE_OFF = "write_off"
    OPENING_ENTRY = "opening_entry"
    EXCHANGE_GAIN_LOSS = "exchange_gain_loss"


class PeriodStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    LOCKED = "locked"


class PartyType(StrEnum):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"


# Accounts that are written ONLY by the system via sub-ledgers / bridge.
# Manual journal posting to these is rejected at the service layer.
CONTROL_ACCOUNT_TYPES: frozenset[str] = frozenset({
    "1100",  # Accounts Receivable
    "2100",  # Accounts Payable
    "1200",  # Inventory
    "2200",  # GRN Accrual
})

# Normal side per account type — determines whether a debit or credit increases
# the account balance.
NORMAL_SIDE_MAP: dict[AccountType, AccountNormalSide] = {
    AccountType.ASSET: AccountNormalSide.DEBIT,
    AccountType.LIABILITY: AccountNormalSide.CREDIT,
    AccountType.EQUITY: AccountNormalSide.CREDIT,
    AccountType.REVENUE: AccountNormalSide.CREDIT,
    AccountType.COGS: AccountNormalSide.DEBIT,
    AccountType.OPEX: AccountNormalSide.DEBIT,
}

# Starter Chart of Accounts — seeded by migration.
STARTER_COA: list[tuple[str, str, AccountType, bool]] = [
    # Assets 1xxx
    ("1010", "Petty Cash", AccountType.ASSET, False),
    ("1020", "Bank Account", AccountType.ASSET, False),
    ("1100", "Accounts Receivable", AccountType.ASSET, True),
    ("1200", "Inventory", AccountType.ASSET, True),
    ("1300", "Prepaid Expenses", AccountType.ASSET, False),
    # Liabilities 2xxx
    ("2100", "Accounts Payable", AccountType.LIABILITY, True),
    ("2200", "GRN Accrual", AccountType.LIABILITY, True),
    ("2300", "Accrued Expenses", AccountType.LIABILITY, False),
    # Equity 3xxx
    ("3100", "Share Capital", AccountType.EQUITY, False),
    ("3200", "Retained Earnings", AccountType.EQUITY, False),
    ("3300", "Current Year Earnings", AccountType.EQUITY, False),
    # Revenue 4xxx
    ("4100", "Sales Revenue", AccountType.REVENUE, False),
    ("4200", "Other Revenue", AccountType.REVENUE, False),
    ("4300", "Realised FX Gain", AccountType.REVENUE, False),
    # Cost of Sales 5xxx
    ("5100", "Cost of Goods Sold", AccountType.COGS, False),
    ("5200", "Stock Write-Off", AccountType.COGS, False),
    # Operating Expenses 6xxx
    ("6100", "Shipping & Freight", AccountType.OPEX, False),
    ("6200", "Bank Charges", AccountType.OPEX, False),
    ("6300", "Realised FX Loss", AccountType.OPEX, False),
    ("6400", "Rounding Difference", AccountType.OPEX, False),
    ("6500", "General Expenses", AccountType.OPEX, False),
]
