"""Fulfilment module constants."""

from enum import StrEnum


class SOStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    DISPATCHED = "dispatched"
    INVOICED = "invoiced"
    CANCELLED = "cancelled"


class DispatchStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
