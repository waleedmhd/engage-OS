"""User management endpoints — all admin-only.

Router commits the unit of work after the service flushes (Msg-C4).
Mutating endpoints carry both the user write and the audit append in
one transaction so the trail rolls back with the action.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.users.schemas import (
    PasswordResetRequest,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserSectionsResponse,
    UserSectionsUpdateRequest,
    UserUpdateRequest,
)
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserListResponse)
async def list_users(
    role: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> UserListResponse:
    return await UserService(session).list_users(
        role=role, is_active=is_active, q=q, limit=limit, offset=offset
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> UserResponse:
    result = await UserService(session).create_user(
        payload, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> UserResponse:
    return await UserService(session).get_user(user_id)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> UserResponse:
    result = await UserService(session).update_user(
        user_id, payload, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: uuid.UUID,
    payload: PasswordResetRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> None:
    await UserService(session).reset_password(
        user_id, payload.password, actor_id=current_user.id
    )
    await session.commit()


@router.get("/{user_id}/sections", response_model=UserSectionsResponse)
async def get_user_sections(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> UserSectionsResponse:
    return await UserService(session).get_user_sections(user_id)


@router.put("/{user_id}/sections", response_model=UserSectionsResponse)
async def update_user_sections(
    user_id: uuid.UUID,
    payload: UserSectionsUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> UserSectionsResponse:
    result = await UserService(session).update_user_sections(
        user_id, payload, actor_id=current_user.id
    )
    await session.commit()
    return result
