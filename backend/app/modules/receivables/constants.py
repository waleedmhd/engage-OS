"""Receivables (AR) module constants — invoice/payment/credit-note statuses, ageing buckets."""

from enum import StrEnum


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    CHEQUE = "cheque"
    CREDIT_CARD = "credit_card"


class PaymentStatus(StrEnum):
    CLEARED = "cleared"
    UNCLEARED = "uncleared"
    VOID = "void"


class CreditNoteStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    VOID = "void"


class CreditNoteReason(StrEnum):
    GOODS_RETURNED = "goods_returned"
    PRICE_ADJUSTMENT = "price_adjustment"
    DAMAGED_GOODS = "damaged_goods"
    OTHER = "other"


# Ageing buckets: (label, min_days_overdue, max_days_overdue).
# max_days_overdue is None for the "and older" bucket.
AGEING_BUCKETS: list[tuple[str, int, int | None]] = [
    ("current", 0, 0),
    ("1_30", 1, 30),
    ("31_60", 31, 60),
    ("61_90", 61, 90),
    ("over_90", 91, None),
]
