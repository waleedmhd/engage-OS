"""Settings endpoints (DSD §7.1) — all admin-only.

Router commits the unit of work after the service flushes (Msg-C4).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_role_db
from app.modules.settings.schemas import (
    AISettingsResponse,
    AISettingsUpdateRequest,
    OperationalSettingsResponse,
    OperationalSettingsUpdateRequest,
    SettingResponse,
    SettingUpdateRequest,
)
from app.modules.settings.service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[SettingResponse])
async def list_settings(
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> list[SettingResponse]:
    return await SettingsService(session).list_settings()


@router.get("/ai", response_model=AISettingsResponse)
async def get_ai_settings(
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> AISettingsResponse:
    return await SettingsService(session).get_ai_settings()


@router.put("/ai", response_model=AISettingsResponse)
async def update_ai_settings(
    payload: AISettingsUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> AISettingsResponse:
    result = await SettingsService(session).update_ai_settings(
        payload, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.get("/operational", response_model=OperationalSettingsResponse)
async def get_operational_settings(
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> OperationalSettingsResponse:
    return await SettingsService(session).get_operational_settings()


@router.put("/operational", response_model=OperationalSettingsResponse)
async def update_operational_settings(
    payload: OperationalSettingsUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> OperationalSettingsResponse:
    result = await SettingsService(session).update_operational_settings(
        payload, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> SettingResponse:
    return await SettingsService(session).get_setting(key)


@router.put("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    payload: SettingUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role_db("admin")),
) -> SettingResponse:
    result = await SettingsService(session).set_setting(
        key, payload.value, actor_id=current_user.id
    )
    await session.commit()
    return result


@router.get("/export/chat-history")
async def export_chat_history(
    session: AsyncSession = Depends(get_db_session),
    _user=Depends(require_role_db("admin")),
) -> Response:
    """Download all conversations as JSONL (admin-only)."""
    from datetime import datetime, timezone

    from app.modules.settings.service import ChatExportService

    svc = ChatExportService(session)
    body = await svc.build_export()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return Response(
        content=body,
        media_type="application/x-jsonlines",
        headers={
            "Content-Disposition": f'attachment; filename="chat-history-{timestamp}.jsonl"',
        },
    )
