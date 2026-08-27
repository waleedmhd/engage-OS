"""AI module request/response wrappers.

Two read surfaces + two internal models:

* ``AIDecisionResponse`` — slim legacy DTO; not currently used by any
  router. Kept for callers that want a non-leaky decision summary.
* ``AIEventResponse`` — admin inspection of ``ai_events`` rows (DSD §5.1,
  §4.3, §10). Exposes the full Claude request/response JSON because the
  endpoint is admin-only — request bodies include message history that
  may contain customer PII, so role-gating at the router is the
  containment boundary.
* ``AIRequest`` — internal model for the cascade router input.
* ``AIDecision`` — validates Claude's emit_decision tool output before
  mapping to the orchestrator's ``Decision`` dataclass.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AIDecisionResponse(BaseModel):
    conversation_id: str
    intent: str = ""
    confidence: float = 0.0
    requires_approval: bool = False
    escalate: bool = False


class AIEventResponse(BaseModel):
    """Admin-visible projection of an ``ai_events`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    intent: str | None = None
    confidence: float | None = None
    latency_ms: int | None = None
    cost_estimate: float | None = None
    error: str | None = None
    created_at: datetime
    request: dict[str, Any] = {}
    response: dict[str, Any] = {}

    @field_validator("confidence", "cost_estimate", mode="before")
    @classmethod
    def _decimal_to_float(cls, v: Any) -> Any:
        # Numeric columns come back as Decimal; coerce so JSON output is
        # numeric rather than a string.
        if isinstance(v, Decimal):
            return float(v)
        return v


# ----------------------------------------------------------------- internal models


class AIRequest(BaseModel):
    """Input to the cascade router (internal, not exposed via HTTP API)."""
    conversation_id: str = ""
    contact_context: dict[str, Any] = Field(default_factory=dict)
    message_history: list[dict[str, Any]] = Field(default_factory=list)
    incoming_message: str = ""
    allowed_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    client_memory: str | None = None


class AIDecision(BaseModel):
    """Structured decision from Claude's emit_decision tool, validated before
    mapping to the orchestrator's ``Decision`` dataclass."""
    reply: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    intent: str = ""
    suggested_tags: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    escalate: bool = False
    send_contact_card: bool = False
    send_business_card_image: bool = False
