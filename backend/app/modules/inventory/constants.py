"""Inventory constants — enums for items, stock units, warehouses."""

from enum import StrEnum


class ItemNature(StrEnum):
    SERIALIZED = "serialized"
    BULK = "bulk"


class StockUnitStatus(StrEnum):
    ON_ORDER = "ON_ORDER"
    IN_STOCK = "IN_STOCK"
    IN_TRANSIT = "IN_TRANSIT"
    SOLD = "SOLD"
    SCRAPPED = "SCRAPPED"
    RETURNED = "RETURNED"


class ValuationMethod(StrEnum):
    SPECIFIC_ID = "specific_identification"
    FIFO = "fifo"
    MOVING_AVG = "moving_average"


class StockVoucherType(StrEnum):
    GRN = "grn"
    DISPATCH = "dispatch"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    COUNT = "stock_count"
    OPENING = "opening"


class AdjustmentReason(StrEnum):
    DAMAGE = "damage"
    LOSS = "loss"
    FOUND = "found"
    EXPIRY = "expiry"
    OTHER = "other"


class TransferStatus(StrEnum):
    DRAFT = "draft"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class StockCountStatus(StrEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
