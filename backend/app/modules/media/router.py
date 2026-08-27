"""Media API endpoints — upload and serve."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_db, get_db_session
from app.modules.media.schemas import MediaAssetResponse
from app.modules.media.service import MediaService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/upload", response_model=MediaAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(get_current_user_db),
) -> MediaAssetResponse:
    service = MediaService(session)
    data = await file.read()
    asset = await service.upload(
        filename=file.filename or "unnamed",
        content_type=file.content_type or "application/octet-stream",
        file_data=data,
    )
    await session.commit()
    return asset


@router.get("/{asset_id}/file")
async def serve_media(
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    service = MediaService(session)
    asset = await service.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")

    path = service.resolve_path(asset.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Media file not found on disk")

    return FileResponse(
        path=str(path),
        media_type=asset.mime_type or "application/octet-stream",
        filename=path.name,
    )
