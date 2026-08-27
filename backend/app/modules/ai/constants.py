"""AI orchestrator decision thresholds + cascade model tiering (DSD §4.3)."""

from enum import StrEnum

CONFIDENCE_AUTO_REPLY_THRESHOLD: float = 0.85
"""Confidence strictly above this value triggers auto-send (FAQ branch)."""


class ModelTier(StrEnum):
    """Cascade router model tiers."""
    BULK = "bulk"            # Haiku — fast/cheap first pass
    ESCALATION = "escalation"  # Sonnet — accurate second opinion
