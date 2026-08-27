"""Categorization endpoints (DSD §6.2).

The router commits the unit of work after the service flushes its writes —
same pattern as contacts and conversations (Conv-C4 / Auth-C1 fixes).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.categorization.schemas import (
    ContactTagResponse,
    TagCreateRequest,
    TagListResponse,
    TagResponse,
    TagSuggestionDecisionRequest,
    TagSuggestionListFilters,
    TagSuggestionResponse,
    TagUpdateRequest,
)
from app.modules.categorization.service import CategorizationService
from app.schemas.common import Page

router = APIRouter(prefix="/categorization", tags=["categorization"])


@router.get("/tags", response_model=TagListResponse)
async def list_tags(
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> TagListResponse:
    return await CategorizationService(session).list_tags_paginated(
        q=q, limit=limit, offset=offset
    )


@router.post(
    "/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tag(
    payload: TagCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> TagResponse:
    result = await CategorizationService(session).create_tag(
        payload, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.patch("/tags/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: uuid.UUID,
    payload: TagUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> TagResponse:
    result = await CategorizationService(session).update_tag(
        tag_id, payload, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> Response:
    await CategorizationService(session).delete_tag(
        tag_id, actor_id=current_user.id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/contacts/{contact_id}/tags",
    response_model=list[ContactTagResponse],
)
async def list_contact_tags(
    contact_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> list[ContactTagResponse]:
    links = await CategorizationService(session).list_contact_tags(contact_id)
    return [ContactTagResponse.model_validate(link) for link in links]


@router.post(
    "/contacts/{contact_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def apply_contact_tag(
    contact_id: uuid.UUID,
    tag_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> Response:
    await CategorizationService(session).apply_tag(
        contact_id, tag_id, actor_id=current_user.id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/contacts/{contact_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_contact_tag(
    contact_id: uuid.UUID,
    tag_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> Response:
    await CategorizationService(session).remove_tag(
        contact_id, tag_id, actor_id=current_user.id
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tag-suggestions", response_model=Page[TagSuggestionResponse])
async def list_tag_suggestions(
    filters: TagSuggestionListFilters = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin", "agent")),
) -> Page[TagSuggestionResponse]:
    items, total = await CategorizationService(session).list_suggestions(
        status=filters.status,
        contact_id=filters.contact_id,
        page=page,
        page_size=page_size,
    )
    return Page[TagSuggestionResponse](
        items=[TagSuggestionResponse.model_validate(s) for s in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/tag-suggestions/{suggestion_id}/approve",
    response_model=TagSuggestionResponse,
)
async def approve_tag_suggestion(
    suggestion_id: uuid.UUID,
    payload: TagSuggestionDecisionRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> TagSuggestionResponse:
    note = payload.note if payload else None
    suggestion = await CategorizationService(session).approve(
        suggestion_id,
        reviewer_id=current_user.id,
        note=note,
    )
    await session.commit()
    return TagSuggestionResponse.model_validate(suggestion)


@router.post(
    "/tag-suggestions/{suggestion_id}/reject",
    response_model=TagSuggestionResponse,
)
async def reject_tag_suggestion(
    suggestion_id: uuid.UUID,
    payload: TagSuggestionDecisionRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin", "agent")),
) -> TagSuggestionResponse:
    note = payload.note if payload else None
    suggestion = await CategorizationService(session).reject(
        suggestion_id,
        reviewer_id=current_user.id,
        note=note,
    )
    await session.commit()
    return TagSuggestionResponse.model_validate(suggestion)
