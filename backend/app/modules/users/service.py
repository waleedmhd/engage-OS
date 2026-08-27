"""User-management service (admin surface).

Async; **flush only** — the router commits the unit of work (Msg-C4).
Every mutation writes an `AuditRepository.append` row in the same
session so config changes are covered by the §9 audit trail and roll
back together with the user write.

Guardrails (raise `ConflictError`):

* Cannot demote-self or deactivate-self (ERR_CANNOT_MODIFY_SELF).
* Last-active-admin guard (ERR_LAST_ACTIVE_ADMIN) — checked against
  the count of *other* active admins, so demoting / deactivating the
  last one is blocked.

Refresh tokens are revoked in the same session whenever an update is
"lockout-effective" (deactivation, admin → agent demotion, password
reset). Stateless JWTs remain valid until natural expiry — that
invariant is preserved.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password
from app.modules.audit.constants import ActorType, AuditAction
from app.modules.audit.repository import AuditRepository
from app.modules.auth.constants import UserRole
from app.modules.auth.models import User
from app.modules.auth.permission_models import ALL_SECTIONS, DEFAULT_AGENT_SECTIONS
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.users.constants import (
    AUDIT_ACTION_RESET_PASSWORD,
    AUDIT_ENTITY_TYPE,
    ERR_CANNOT_MODIFY_SELF,
    ERR_LAST_ACTIVE_ADMIN,
    ERR_NO_CHANGES,
    PASSWORD_REDACTED,
)
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import (
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserSectionsResponse,
    UserSectionsUpdateRequest,
    UserUpdateRequest,
)


def _user_state(user: User) -> dict[str, Any]:
    """Dict used for audit before/after. Never includes password material."""
    return {
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "is_active": user.is_active,
    }


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)
        self._audit = AuditRepository(session)

    # ------------------------------------------------------------------ reads

    async def list_users(
        self,
        *,
        role: str | None = None,
        is_active: bool | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> UserListResponse:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        items = await self.repo.list_paginated(
            role=role, is_active=is_active, q=q, limit=limit, offset=offset
        )
        total = await self.repo.count(role=role, is_active=is_active, q=q)
        return UserListResponse(
            items=[UserResponse.model_validate(u) for u in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_user(self, user_id: uuid.UUID) -> UserResponse:
        user = await self.repo.get(user_id)
        if user is None:
            raise NotFoundError(f"User:{user_id}")
        return UserResponse.model_validate(user)

    # ----------------------------------------------------------------- writes

    async def create_user(
        self, payload: UserCreateRequest, *, actor_id: uuid.UUID
    ) -> UserResponse:
        existing = await self.repo.get_by_email(payload.email)
        if existing is not None:
            raise ConflictError("email_taken")

        user = await self.repo.create(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            role=payload.role.value,
            name=payload.name,
        )

        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.CREATE.value,
            entity_type=AUDIT_ENTITY_TYPE,
            entity_id=user.id,
            before_state=None,
            after_state=_user_state(user),
        )
        return UserResponse.model_validate(user)

    async def update_user(
        self,
        user_id: uuid.UUID,
        payload: UserUpdateRequest,
        *,
        actor_id: uuid.UUID,
    ) -> UserResponse:
        user = await self.repo.get(user_id)
        if user is None:
            raise NotFoundError(f"User:{user_id}")

        # Build the diff (only fields that actually change).
        before = _user_state(user)
        proposed = payload.model_dump(exclude_unset=True)
        if "role" in proposed and proposed["role"] is not None:
            proposed["role"] = (
                proposed["role"].value
                if isinstance(proposed["role"], UserRole)
                else proposed["role"]
            )
        diff: dict[str, Any] = {
            k: v for k, v in proposed.items() if v is not None and getattr(user, k) != v
        }
        if not diff:
            raise ConflictError(ERR_NO_CHANGES)

        # Email uniqueness — guard against the constraint with a clearer error.
        if "email" in diff:
            taken = await self.repo.get_by_email(str(diff["email"]))
            if taken is not None and taken.id != user.id:
                raise ConflictError("email_taken")

        # Self-modify guard.
        is_self = user.id == actor_id
        if is_self:
            if "role" in diff and diff["role"] != UserRole.ADMIN.value:
                raise ConflictError(ERR_CANNOT_MODIFY_SELF)
            if "is_active" in diff and diff["is_active"] is False:
                raise ConflictError(ERR_CANNOT_MODIFY_SELF)

        # Last-admin guard. Triggered by demote-from-admin or deactivate-admin.
        demoting = (
            "role" in diff
            and user.role == UserRole.ADMIN.value
            and diff["role"] != UserRole.ADMIN.value
        )
        deactivating_admin = (
            "is_active" in diff
            and diff["is_active"] is False
            and user.role == UserRole.ADMIN.value
            and user.is_active is True
        )
        if (demoting or deactivating_admin) and user.is_active:
            others = await self.repo.count_other_active_admins(user.id)
            if others == 0:
                raise ConflictError(ERR_LAST_ACTIVE_ADMIN)

        updated = await self.repo.apply_updates(user, diff)

        # Token revocation rides the same transaction.
        lockout = demoting or (
            "is_active" in diff and diff["is_active"] is False
        )
        if lockout:
            await self._tokens.revoke_all_for_user(updated.id)

        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.UPDATE.value,
            entity_type=AUDIT_ENTITY_TYPE,
            entity_id=updated.id,
            before_state=before,
            after_state=_user_state(updated),
        )
        return UserResponse.model_validate(updated)

    async def reset_password(
        self,
        user_id: uuid.UUID,
        new_password: str,
        *,
        actor_id: uuid.UUID,
    ) -> None:
        user = await self.repo.get(user_id)
        if user is None:
            raise NotFoundError(f"User:{user_id}")

        await self.repo.set_password(user, hash_password(new_password))
        await self._tokens.revoke_all_for_user(user.id)

        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AUDIT_ACTION_RESET_PASSWORD,
            entity_type=AUDIT_ENTITY_TYPE,
            entity_id=user.id,
            before_state={"password": PASSWORD_REDACTED},
            after_state={"password": PASSWORD_REDACTED},
        )

    # ---------------------------------------------------------- section access

    async def get_user_sections(self, user_id: uuid.UUID) -> UserSectionsResponse:
        user = await self.repo.get(user_id)
        if user is None:
            raise NotFoundError(f"User:{user_id}")
        if user.role == UserRole.ADMIN.value:
            return UserSectionsResponse(sections=list(ALL_SECTIONS))
        stored = await self.repo.get_accessible_sections(user_id)
        if not stored:
            return UserSectionsResponse(sections=list(DEFAULT_AGENT_SECTIONS))
        return UserSectionsResponse(sections=sorted(
            stored, key=lambda k: ALL_SECTIONS.index(k) if k in ALL_SECTIONS else 999
        ))

    async def update_user_sections(
        self,
        user_id: uuid.UUID,
        payload: UserSectionsUpdateRequest,
        *,
        actor_id: uuid.UUID,
    ) -> UserSectionsResponse:
        user = await self.repo.get(user_id)
        if user is None:
            raise NotFoundError(f"User:{user_id}")

        unknown = [k for k in payload.sections if k not in ALL_SECTIONS]
        if unknown:
            raise ValidationError(
                f"Unknown section keys: {', '.join(sorted(unknown))}"
            )

        before_sections = await self.repo.get_accessible_sections(user_id)
        await self.repo.set_accessible_sections(user_id, payload.sections)

        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.UPDATE.value,
            entity_type="user_sections",
            entity_id=user_id,
            before_state={"sections": before_sections},
            after_state={"sections": payload.sections},
        )
        return UserSectionsResponse(sections=payload.sections)
