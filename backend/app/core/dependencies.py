"""Reusable FastAPI dependencies (DB session, settings, current user, role gate).

Dependencies declared here are imported by `app.api.deps` so that each module
router has a single import path: `from app.api.deps import ...`.

Modularity note: this module imports from ``app.modules.auth`` (User model,
UserRole enum, UserPermission model) via lazy imports inside function bodies.
This is by design — the FastAPI dependency injection layer is the composition
root, analogous to a DI container's registration phase. Domain modules should
NOT import from here; this module imports from domain modules to wire them
into the request pipeline. The lazy imports prevent import-time circular
dependencies while preserving the runtime behavior.
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import decode_access_token
from app.db.session import async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def get_settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user_claims(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Decode the bearer token and return the JWT claims dict."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing_bearer_token")
    token = authorization.split(" ", 1)[1].strip()
    return decode_access_token(token, settings=settings)


CurrentUserClaims = Annotated[dict, Depends(get_current_user_claims)]

# Backwards-compatible alias (used by existing routers that only need claims)
get_current_user = get_current_user_claims
CurrentUser = CurrentUserClaims


async def get_current_user_db(
    claims: CurrentUserClaims,
    db: DbSession,
):
    """Load the full User row from DB using the JWT subject claim.

    Raises AuthError if the user does not exist or is inactive.
    """
    from app.modules.auth.models import User

    user_id_str = claims.get("sub")
    if not user_id_str:
        raise AuthError("invalid_token")
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise AuthError("invalid_token") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("account_inactive")
    return user


CurrentUserDB = Annotated[object, Depends(get_current_user_db)]


def require_role(*roles: str):
    """Return a dependency that enforces one of the given roles.

    Works with both JWT claims dicts (``CurrentUserClaims``) and ORM User
    objects (``CurrentUserDB``).
    """

    async def _checker(claims: CurrentUserClaims) -> dict:
        user_role = claims.get("role")
        if user_role not in roles:
            raise ForbiddenError("role_required", details={"required": list(roles)})
        return claims

    return _checker


def require_role_db(*roles: str):
    """Return a dependency that enforces one of the given roles and returns the User ORM object.

    Use instead of ``require_role`` when the endpoint needs ``user.id`` or
    other ORM attributes — ``require_role`` returns a plain claims dict.
    """

    async def _checker(claims: CurrentUserClaims, user=Depends(get_current_user_db)):
        user_role = claims.get("role")
        if user_role not in roles:
            raise ForbiddenError("role_required", details={"required": list(roles)})
        return user

    return _checker


def require_permission(*codes: str):
    """Return a FastAPI dependency that enforces at least one of *codes*.

    Admin is an implicit wildcard — passes without checking the grants table.
    Every other role must have an explicit ``UserPermission`` row.

    Usage in a router:
        _perm = Depends(require_permission("erp_fin.journal.post"))
    """

    async def _checker(
        claims: CurrentUserClaims,
        db: DbSession,
        user=Depends(get_current_user_db),
    ):
        from app.modules.auth.constants import UserRole

        if claims.get("role") == UserRole.ADMIN.value:
            return user

        from sqlalchemy import select

        from app.modules.auth.permission_models import UserPermission

        stmt = select(UserPermission).where(
            UserPermission.user_id == user.id,
            UserPermission.permission_code.in_(codes),
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ForbiddenError(
                "permission_denied",
                details={"required": list(codes)},
            )
        return user

    return _checker
