"""Payables module constants — bill status, payment method, debit note reason, ageing buckets."""

from enum import StrEnum


class BillStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    CHEQUE = "cheque"


class DebitNoteReason(StrEnum):
    GOODS_RETURNED = "goods_returned"
    PRICE_ADJUSTMENT = "price_adjustment"
    DAMAGED_GOODS = "damaged_goods"
    OTHER = "other"


class PaymentStatus(StrEnum):
    CLEARED = "cleared"
    UNCLEARED = "uncleared"
    VOID = "void"


class DebitNoteStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    VOID = "void"


AGEING_BUCKETS: list[tuple[str, int, int | None]] = [
    ("current", 0, 0),
    ("1_30", 1, 30),
    ("31_60", 31, 60),
    ("61_90", 61, 90),
    ("over_90", 91, None),
]
