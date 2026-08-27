"""Campaign endpoints (DSD §6.2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, DbSession, get_db_session, require_role_db
from app.modules.campaigns.constants import CampaignStatus, CampaignType
from app.modules.campaigns.repository import (
    CampaignRecipientRepository,
    CampaignRepository,
)
from app.modules.campaigns.schemas import (
    CampaignCategoryCreateRequest,
    CampaignCategoryListResponse,
    CampaignCategoryResponse,
    CampaignCategoryUpdateRequest,
    CampaignCreateRequest,
    CampaignLaunchRequest,
    CampaignRecipientResponse,
    CampaignReportResponse,
    CampaignResponse,
    CampaignUpdateRequest,
    CampaignValidationResponse,
)
from app.modules.campaigns.service import CampaignCategoryService, CampaignService
from app.modules.campaigns.tasks import dispatch_campaign_task
from app.schemas.common import Page

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
categories_router = APIRouter(
    prefix="/campaign-categories", tags=["campaign-categories"]
)


def _actor_id(user: dict) -> uuid.UUID | None:
    sub = user.get("sub")
    if not sub:
        return None
    try:
        return uuid.UUID(sub)
    except ValueError:
        return None


@router.get("", response_model=Page[CampaignResponse])
async def list_campaigns(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
) -> Page[CampaignResponse]:
    repo = CampaignRepository(db)
    items, total = await repo.list_campaigns(
        page=page, page_size=page_size, status=status_filter
    )
    return Page[CampaignResponse](
        items=[CampaignResponse.model_validate(c) for c in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreateRequest,
    db: DbSession,
    user: CurrentUser,
) -> CampaignResponse:
    service = CampaignService(db)
    campaign = await service.create_campaign(payload, actor_id=_actor_id(user))
    await db.commit()
    return CampaignResponse.model_validate(campaign)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> CampaignResponse:
    service = CampaignService(db)
    campaign = await service._get_or_404(campaign_id)
    return CampaignResponse.model_validate(campaign)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignUpdateRequest,
    db: DbSession,
    user: CurrentUser,
) -> CampaignResponse:
    service = CampaignService(db)
    campaign = await service.update_campaign(
        campaign_id, payload, actor_id=_actor_id(user)
    )
    await db.commit()
    return CampaignResponse.model_validate(campaign)


@router.post("/{campaign_id}/validate", response_model=CampaignValidationResponse)
async def validate_campaign(
    campaign_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> CampaignValidationResponse:
    service = CampaignService(db)
    result = await service.validate_campaign(campaign_id, actor_id=_actor_id(user))
    await db.commit()
    return result


@router.post("/{campaign_id}/launch", response_model=CampaignResponse)
async def launch_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignLaunchRequest,
    db: DbSession,
    user: CurrentUser,
) -> CampaignResponse:
    """Launch a campaign.

    Msg-C4 commit ordering:
      1. service flushes lifecycle changes
      2. router commits
      3. router dispatches dispatch_campaign_task only after commit
    """
    service = CampaignService(db)
    campaign = await service.launch_campaign(campaign_id, actor_id=_actor_id(user))
    await db.commit()

    if (
        campaign.type == CampaignType.IMMEDIATE.value
        and campaign.status == CampaignStatus.QUEUED.value
    ):
        dispatch_campaign_task.delay(str(campaign.id))

    return CampaignResponse.model_validate(campaign)


@router.post("/{campaign_id}/cancel", response_model=CampaignResponse)
async def cancel_campaign(
    campaign_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> CampaignResponse:
    service = CampaignService(db)
    campaign = await service.cancel_campaign(campaign_id, actor_id=_actor_id(user))
    await db.commit()
    return CampaignResponse.model_validate(campaign)


@router.get("/{campaign_id}/report", response_model=CampaignReportResponse)
async def get_report(
    campaign_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> CampaignReportResponse:
    service = CampaignService(db)
    return await service.get_report(campaign_id)


@router.get(
    "/{campaign_id}/recipients",
    response_model=Page[CampaignRecipientResponse],
)
async def list_recipients(
    campaign_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
) -> Page[CampaignRecipientResponse]:
    repo = CampaignRecipientRepository(db)
    items, total = await repo.list_for_campaign(
        campaign_id,
        page=page,
        page_size=page_size,
        status=status_filter,
    )
    return Page[CampaignRecipientResponse](
        items=[CampaignRecipientResponse.model_validate(r) for r in items],
        page=page,
        page_size=page_size,
        total=total,
    )


# ---------------------------------------------------------- campaign_categories

@categories_router.get("", response_model=CampaignCategoryListResponse)
async def list_campaign_categories(
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> CampaignCategoryListResponse:
    return await CampaignCategoryService(session).list_categories(
        q=q, limit=limit, offset=offset
    )


@categories_router.post(
    "",
    response_model=CampaignCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign_category(
    payload: CampaignCategoryCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> CampaignCategoryResponse:
    result = await CampaignCategoryService(session).create_category(
        payload, actor_id=current_user.id
    )
    await session.commit()
    return result


@categories_router.get(
    "/{category_id}", response_model=CampaignCategoryResponse
)
async def get_campaign_category(
    category_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> CampaignCategoryResponse:
    return await CampaignCategoryService(session).get_category(category_id)


@categories_router.patch(
    "/{category_id}", response_model=CampaignCategoryResponse
)
async def update_campaign_category(
    category_id: uuid.UUID,
    payload: CampaignCategoryUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> CampaignCategoryResponse:
    result = await CampaignCategoryService(session).update_category(
        category_id, payload, actor_id=current_user.id
    )
    await session.commit()
    return result


@categories_router.delete(
    "/{category_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_campaign_category(
    category_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> Response:
    await CampaignCategoryService(session).delete_category(
        category_id, actor_id=current_user.id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
