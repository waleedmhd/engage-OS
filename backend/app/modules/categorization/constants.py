"""Categorization enums and the predefined tag taxonomy (DSD §4.6)."""

from enum import StrEnum


class TagSuggestionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# Predefined fixed taxonomy. Persisted to the `tags` table on first migration.
PREDEFINED_TAGS: tuple[str, ...] = (
    # Engagement policy §6 auto-applied tags (system-derived, no approval):
    "NEEDS_FOLLOW_UP",
    "UNRESPONSIVE",
    "UNDELIVERABLE",
    "INVALID_NUMBER",
    "NOT_ON_WHATSAPP",
    "DO_NOT_CONTACT",
    # Existing taxonomy:
    "Buyer",
    "Seller",
    "iPhone Buyer",
    "Samsung Buyer",
    "Bulk Buyer",
    "Warm Lead",
    "Cold Lead",
    "High Intent",
    "Price Sensitive",
    "Returning Customer",
    "VIP",
    "Wholesaler",
    "Retailer",
    "Reseller",
    "Repair Shop",
    "International",
    "Local",
    "Trade-In Interested",
    "Bulk Seller",
    "Spam",
)
