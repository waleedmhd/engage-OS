"""Inventory domain events — consumed by the ledger bridge (async subscribers)."""


class InventoryEvents:
    GRN_CONFIRMED = "inventory.grn_confirmed"
    UNIT_DISPATCHED = "inventory.unit_dispatched"
    ADJUSTMENT_CONFIRMED = "inventory.adjustment_confirmed"
