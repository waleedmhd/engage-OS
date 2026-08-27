"""Analytics endpoints (DSD §6.2, Phase 6).

All routes are **admin-only** — revenue is sensitive.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.analytics.constants import AnalyticsRange
from app.modules.analytics.schemas import (
    AISummary,
    BackfillRequest,
    BackfillResponse,
    CampaignDetailResponse,
    CampaignSummaryRow,
    ConversionSummary,
    CostSummary,
    ResponsivenessSummary,
    ROISummary,
    TemplateDetailResponse,
    TemplateSummaryRow,
)
from app.modules.analytics.service import AnalyticsService
from app.modules.analytics.tasks import backfill_daily_metrics_task
from app.schemas.common import Page

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/cost", response_model=CostSummary)
async def cost_metrics(
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> CostSummary:
    return await AnalyticsService(session).cost(range)


@router.get("/conversion", response_model=ConversionSummary)
async def conversion_metrics(
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> ConversionSummary:
    return await AnalyticsService(session).conversion(range)


@router.get("/ai", response_model=AISummary)
async def ai_metrics(
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> AISummary:
    return await AnalyticsService(session).ai(range)


@router.get("/roi", response_model=ROISummary)
async def roi_metrics(
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> ROISummary:
    return await AnalyticsService(session).roi(range)


@router.get("/campaigns", response_model=Page[CampaignSummaryRow])
async def list_campaign_metrics(
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> Page[CampaignSummaryRow]:
    items, total, p, ps = await AnalyticsService(session).list_campaigns(
        range, page, page_size
    )
    return Page[CampaignSummaryRow](items=items, page=p, page_size=ps, total=total)


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetailResponse)
async def campaign_detail(
    campaign_id: uuid.UUID,
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> CampaignDetailResponse:
    return await AnalyticsService(session).campaign_detail(campaign_id, range)


@router.get("/templates", response_model=Page[TemplateSummaryRow])
async def list_template_metrics(
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> Page[TemplateSummaryRow]:
    items, total, p, ps = await AnalyticsService(session).list_templates(
        range, page, page_size
    )
    return Page[TemplateSummaryRow](items=items, page=p, page_size=ps, total=total)


@router.get("/templates/{template_id}", response_model=TemplateDetailResponse)
async def template_detail(
    template_id: uuid.UUID,
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> TemplateDetailResponse:
    return await AnalyticsService(session).template_detail(template_id, range)


@router.get("/responsiveness", response_model=ResponsivenessSummary)
async def responsiveness_metrics(
    range: AnalyticsRange = Query(AnalyticsRange.MONTH),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> ResponsivenessSummary:
    return await AnalyticsService(session).responsiveness(range)


@router.post("/backfill", response_model=BackfillResponse, status_code=202)
async def trigger_backfill(
    body: BackfillRequest,
    _user=Depends(require_role_db("admin")),
) -> BackfillResponse:
    """Re-aggregate a date range. Returns immediately with the queued task id."""
    async_result = backfill_daily_metrics_task.delay(
        body.start_date.isoformat(), body.end_date.isoformat()
    )
    return BackfillResponse(
        task_id=async_result.id,
        start_date=body.start_date,
        end_date=body.end_date,
    )
