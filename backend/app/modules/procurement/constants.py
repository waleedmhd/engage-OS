"""Procurement module constants."""

from enum import StrEnum


class POStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class GRNStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
