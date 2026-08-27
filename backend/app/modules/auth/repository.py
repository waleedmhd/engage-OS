"""Auth repository — DB access for users and refresh tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from app.db.repository import BaseRepository
from app.modules.auth.models import RefreshToken, User


class AuthRepository(BaseRepository[User]):
    model = User

    async def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.get(user_id)

    async def create_user(
        self,
        *,
        email: str,
        hashed_password: str,
        role: str,
        name: str | None = None,
    ) -> User:
        return await self.create(
            email=email.lower(),
            hashed_password=hashed_password,
            role=role,
            name=name,
        )

    async def deactivate(self, user_id: uuid.UUID) -> User | None:
        return await self.update(user_id, is_active=False)


class RefreshTokenRepository:
    def __init__(self, session) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, token_id: uuid.UUID) -> None:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked=True)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete_expired(self) -> int:
        stmt = delete(RefreshToken).where(
            RefreshToken.expires_at < datetime.now(UTC)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0
