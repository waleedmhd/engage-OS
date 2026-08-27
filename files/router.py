"""
app/modules/auth/router.py

Fix applied:
  Auth-C1 — AuthService.login() and AuthService.refresh() both called
             repository.flush() internally but never committed the session.
             get_db_session() uses autocommit=False and closes without
             committing. The RefreshToken row was written to the DB buffer
             but never durable — every login succeeded in memory but the
             token could not be verified on subsequent requests because the
             row did not exist.

             Fix: each mutating endpoint calls `await session.commit()`
             explicitly after the service call returns. The session is then
             closed by the dependency injector.

             Why here and not inside the service:
             Per the architecture, service.py owns business logic; the
             transaction boundary belongs to the caller (router or UoW).
             Committing in the router keeps the service unit-testable without
             a live DB transaction.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_db, get_db_session
from app.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    UserResponse,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    Authenticate a user and return access + refresh tokens.

    Auth-C1 fix: session.commit() is called after the service returns so
    the RefreshToken row is durably persisted before the response is sent.
    """
    service = AuthService(session)
    response = await service.login(
        email=payload.email,
        password=payload.password,
    )
    # Auth-C1 fix: commit here — service only flushes (writes to buffer).
    await session.commit()
    return response


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RefreshResponse:
    """
    Rotate a refresh token and return a new access + refresh token pair.

    Auth-C1 fix: commit after rotation so both the revocation of the old
    token and creation of the new token are durably written atomically.
    """
    service = AuthService(session)
    response = await service.refresh(token=payload.refresh_token)
    # Auth-C1 fix: both revoke-old and create-new are flushed inside service;
    # commit here makes both durable in a single transaction.
    await session.commit()
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Revoke a refresh token, preventing future use."""
    service = AuthService(session)
    await service.revoke_token(token=payload.refresh_token)
    await session.commit()


@router.get("/me", response_model=UserResponse)
async def me(
    current_user=Depends(get_current_user_db),
) -> UserResponse:
    """Return the currently authenticated user's profile."""
    return UserResponse.model_validate(current_user)
