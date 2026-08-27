"""User repository for admin CRUD.

Distinct from `AuthRepository` (which serves the login path). Adds
listing with filters, last-admin counting, and uniqueness lookups
needed by the admin surface.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.constants import UserRole
from app.modules.auth.models import User
from app.modules.auth.permission_models import UserAccessibleSection


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ reads

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def _list_stmt(
        self,
        *,
        role: str | None,
        is_active: bool | None,
        q: str | None,
    ):
        stmt = select(User)
        if role is not None:
            stmt = stmt.where(User.role == role)
        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        if q:
            needle = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                or_(User.email.ilike(needle), sa.func.lower(User.name).ilike(needle))
            )
        return stmt

    async def list_paginated(
        self,
        *,
        role: str | None = None,
        is_active: bool | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[User]:
        stmt = (
            self._list_stmt(role=role, is_active=is_active, q=q)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(
        self,
        *,
        role: str | None = None,
        is_active: bool | None = None,
        q: str | None = None,
    ) -> int:
        inner = self._list_stmt(role=role, is_active=is_active, q=q)
        stmt = sa.select(sa.func.count()).select_from(inner.subquery())
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_other_active_admins(self, exclude_id: uuid.UUID) -> int:
        """Active admins excluding the given user id. Used for last-admin guard."""
        stmt = sa.select(sa.func.count()).select_from(
            select(User)
            .where(
                User.role == UserRole.ADMIN.value,
                User.is_active.is_(True),
                User.id != exclude_id,
            )
            .subquery()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # ----------------------------------------------------------------- writes

    async def create(
        self,
        *,
        email: str,
        hashed_password: str,
        role: str,
        name: str | None = None,
    ) -> User:
        user = User(
            email=email.lower(),
            hashed_password=hashed_password,
            role=role,
            name=name,
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def apply_updates(self, user: User, fields: dict[str, Any]) -> User:
        """Mutate `user` with the given field dict and flush.

        Caller is responsible for figuring out which fields actually change.
        Email is lower-cased here so the constraint can be enforced.
        """
        for key, value in fields.items():
            if key == "email" and isinstance(value, str):
                value = value.lower()
            setattr(user, key, value)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def set_password(self, user: User, hashed_password: str) -> User:
        user.hashed_password = hashed_password
        await self.session.flush()
        await self.session.refresh(user)
        return user

    # ------------------------------------------------------------- section access

    async def get_accessible_sections(self, user_id: uuid.UUID) -> list[str]:
        stmt = select(UserAccessibleSection.section_key).where(
            UserAccessibleSection.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_accessible_sections(
        self, user_id: uuid.UUID, sections: list[str]
    ) -> None:
        # Delete existing
        await self.session.execute(
            sa.delete(UserAccessibleSection).where(
                UserAccessibleSection.user_id == user_id
            )
        )
        # Insert new
        for key in sections:
            self.session.add(UserAccessibleSection(user_id=user_id, section_key=key))
        await self.session.flush()
