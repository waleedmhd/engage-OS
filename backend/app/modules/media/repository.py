"""MediaAsset repository — async and sync accessors."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import BaseRepository
from app.modules.media.models import MediaAsset


class MediaAssetRepository(BaseRepository[MediaAsset]):
    model = MediaAsset

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_message_id(self, message_id: uuid.UUID) -> list[MediaAsset]:
        result = await self.session.execute(
            sa.select(MediaAsset).where(MediaAsset.message_id == message_id)
        )
        return list(result.scalars().all())

    def create_sync(self, **kwargs) -> MediaAsset:
        from sqlalchemy.orm import Session as SyncSession

        session: SyncSession = self.session  # type: ignore[assignment]
        asset = MediaAsset(**kwargs)
        session.add(asset)
        session.flush()
        session.refresh(asset)
        return asset
