"""Analytics response schemas (Phase 6)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class CostDailyPoint(BaseModel):
    metric_date: date
    ai_spend_usd: Decimal = Decimal("0")
    message_cost_usd: Decimal = Decimal("0")
    meta_cost_aed: Decimal = Decimal("0")
    tokens_input: int = 0
    tokens_output: int = 0
    total_cost_usd: Decimal = Decimal("0")


class CostSummary(BaseModel):
    range: str
    start_date: date
    end_date: date
    ai_spend_usd: Decimal = Decimal("0")
    message_cost_usd: Decimal = Decimal("0")
    meta_cost_aed: Decimal = Decimal("0")
    tokens_input: int = 0
    tokens_output: int = 0
    total_cost_usd: Decimal = Decimal("0")
    by_day: list[CostDailyPoint] = Field(default_factory=list)


class ConversionDailyPoint(BaseModel):
    metric_date: date
    messages_sent: int = 0
    messages_received: int = 0
    response_rate: float = 0.0


class ConversionSummary(BaseModel):
    range: str
    start_date: date
    end_date: date
    messages_sent: int = 0
    messages_received: int = 0
    messages_delivered: int = 0
    messages_failed: int = 0
    response_rate: float = 0.0
    conversion_rate: float = 0.0
    by_day: list[ConversionDailyPoint] = Field(default_factory=list)


class AISummary(BaseModel):
    range: str
    start_date: date
    end_date: date
    token_spend_usd: Decimal = Decimal("0")
    ai_call_count: int = 0
    ai_error_count: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    avg_latency_ms: int | None = None
    ai_handled_pct: float = 0.0


class CampaignROIRow(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    revenue_usd: Decimal = Decimal("0")
    cost_usd: Decimal = Decimal("0")
    roi: float | None = None


class ROISummary(BaseModel):
    range: str
    start_date: date
    end_date: date
    total_revenue_usd: Decimal = Decimal("0")
    total_cost_usd: Decimal = Decimal("0")
    overall_roi: float | None = None
    top_campaigns: list[CampaignROIRow] = Field(default_factory=list)


class CampaignSummaryRow(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    template_name: str = ""
    recipients_sent: int = 0
    recipients_delivered: int = 0
    recipients_responded: int = 0
    response_rate: float = 0.0
    revenue_usd: Decimal = Decimal("0")
    cost_usd: Decimal = Decimal("0")
    meta_cost_aed: Decimal = Decimal("0")
    tokens_input: int = 0
    tokens_output: int = 0
    roi: float | None = None


class CampaignDailyPoint(BaseModel):
    metric_date: date
    recipients_sent: int = 0
    recipients_delivered: int = 0
    recipients_responded: int = 0
    response_rate: float = 0.0
    revenue_usd: Decimal = Decimal("0")
    cost_usd: Decimal = Decimal("0")
    meta_cost_aed: Decimal = Decimal("0")
    tokens_input: int = 0
    tokens_output: int = 0
    roi: float | None = None


class CampaignDetailResponse(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    range: str
    start_date: date
    end_date: date
    totals: CampaignSummaryRow
    by_day: list[CampaignDailyPoint] = Field(default_factory=list)


class BackfillRequest(BaseModel):
    start_date: date
    end_date: date


class BackfillResponse(BaseModel):
    task_id: str
    start_date: date
    end_date: date


# ---------------------------------------------------------------------------
# Template performance
# ---------------------------------------------------------------------------


class TemplateSummaryRow(BaseModel):
    template_id: uuid.UUID
    template_name: str
    campaigns_used: int = 0
    recipients_sent: int = 0
    recipients_delivered: int = 0
    recipients_responded: int = 0
    response_rate: float = 0.0
    message_cost_usd: Decimal = Decimal("0")
    meta_cost_aed: Decimal = Decimal("0")
    ai_spend_usd: Decimal = Decimal("0")
    tokens_input: int = 0
    tokens_output: int = 0
    total_cost_usd: Decimal = Decimal("0")


class TemplateDailyPoint(BaseModel):
    metric_date: date
    campaigns_used: int = 0
    recipients_sent: int = 0
    recipients_delivered: int = 0
    recipients_responded: int = 0
    response_rate: float = 0.0
    message_cost_usd: Decimal = Decimal("0")
    meta_cost_aed: Decimal = Decimal("0")
    ai_spend_usd: Decimal = Decimal("0")
    tokens_input: int = 0
    tokens_output: int = 0
    total_cost_usd: Decimal = Decimal("0")


class TemplateDetailResponse(BaseModel):
    template_id: uuid.UUID
    template_name: str
    range: str
    start_date: date
    end_date: date
    totals: TemplateSummaryRow
    by_day: list[TemplateDailyPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Responsiveness (time-of-day / day-of-week)
# ---------------------------------------------------------------------------


class HourlyPatternPoint(BaseModel):
    hour: int
    messages_sent: int = 0
    messages_received: int = 0
    response_rate: float = 0.0


class DailyPatternPoint(BaseModel):
    day_of_week: int  # 0=Monday .. 6=Sunday
    messages_sent: int = 0
    messages_received: int = 0
    response_rate: float = 0.0


class ResponsivenessSummary(BaseModel):
    range: str
    start_date: date
    end_date: date
    by_hour: list[HourlyPatternPoint] = Field(default_factory=list)
    by_day_of_week: list[DailyPatternPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Legacy aliases — keep the placeholder names exported so any code that
# imported them in Phase 0 still resolves. They map to the real shapes above.
# ---------------------------------------------------------------------------

CostMetricsResponse = CostSummary
ConversionMetricsResponse = ConversionSummary
AIMetricsResponse = AISummary
