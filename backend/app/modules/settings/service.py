"""Settings service (DSD §7.1).

Async; **flush only** — the router commits the unit of work (Msg-C4).
Every mutation writes an audit row via ``AuditRepository.append`` in the
same session so config changes are covered by the §9 audit trail and roll
back together with the setting write.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.conversations.models import Conversation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.audit.constants import ActorType, AuditAction
from app.modules.audit.repository import AuditRepository
from app.modules.settings.constants import (
    AI_SETTING_DEFAULTS,
    AI_TEST_NUMBERS_DEFAULT,
    OPERATIONAL_SETTING_DEFAULTS,
    SETTING_AI_AUTO_SEND_ENABLED,
    SETTING_AI_BUSINESS_CARD_MEDIA_ID,
    SETTING_AI_KILL_SWITCH,
    SETTING_AI_RESPONSE_GENERATION_ENABLED,
    SETTING_AI_TAG_SUGGESTIONS_ENABLED,
    SETTING_AI_TEST_NUMBERS,
    SETTING_OPS_BUSINESS_HOURS,
    SETTING_OPS_CAMPAIGN_DAILY_CAP,
    SETTING_OPS_DELIVERY_FAILURE_RETRY,
    SETTING_OPS_READ_ONLY_MODE,
    SETTING_OPS_TIMEZONE,
)
from app.modules.settings.repository import SettingsRepository
from app.modules.settings.schemas import (
    AISettingsResponse,
    AISettingsUpdateRequest,
    OperationalSettingsResponse,
    OperationalSettingsUpdateRequest,
    SettingResponse,
)


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SettingsRepository(session)
        self._audit = AuditRepository(session)

    async def list_settings(
        self, *, scope: str | None = None
    ) -> list[SettingResponse]:
        rows = await self.repo.list_all(scope=scope)
        return [
            SettingResponse(key=r.key, value=r.value, scope=r.scope) for r in rows
        ]

    async def get_setting(
        self, key: str, *, scope: str = "global"
    ) -> SettingResponse:
        row = await self.repo.get(key, scope=scope)
        if row is None:
            raise NotFoundError(f"AppSetting:{key}")
        return SettingResponse(key=row.key, value=row.value, scope=row.scope)

    async def set_setting(
        self,
        key: str,
        value: Any,
        *,
        scope: str = "global",
        actor_id: uuid.UUID | None = None,
    ) -> SettingResponse:
        existing = await self.repo.get(key, scope=scope)
        before = {"value": existing.value} if existing is not None else None

        row = await self.repo.upsert(key, value, scope=scope)

        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.UPDATE.value,
            entity_type="AppSetting",
            entity_id=row.id,
            before_state=before,
            after_state={"value": row.value, "scope": row.scope, "key": row.key},
        )
        return SettingResponse(key=row.key, value=row.value, scope=row.scope)

    async def _resolve_bool(self, key: str) -> bool:
        row = await self.repo.get(key, scope="global")
        if (
            row is None
            or not isinstance(row.value, dict)
            or "enabled" not in row.value
        ):
            return AI_SETTING_DEFAULTS[key]
        return bool(row.value["enabled"])

    async def _resolve_str(self, key: str, field: str) -> str | None:
        row = await self.repo.get(key, scope="global")
        if row is None or not isinstance(row.value, dict):
            return None
        val = row.value.get(field)
        return str(val) if val else None

    async def _validate_business_card_media(self, raw_asset_id: str) -> None:
        """Verify that the given UUID points to a MediaAsset with file_data.

        Raises ValueError with a clear message if the asset is missing or
        has no file_data blob (e.g. the seed-created row that predates the
        file_data column).
        """
        import uuid as _uuid

        from sqlalchemy.orm import undefer

        from app.modules.media.models import MediaAsset

        try:
            asset_id = _uuid.UUID(raw_asset_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"Invalid UUID: {raw_asset_id!r}") from exc

        asset = await self.session.get(
            MediaAsset,
            asset_id,
            options=[undefer(MediaAsset.file_data)],
        )
        if asset is None:
            raise ValueError(
                f"No MediaAsset found with id {asset_id}. "
                "Upload the business card image first via the Media Upload endpoint."
            )
        if not asset.file_data:
            raise ValueError(
                f"MediaAsset {asset_id} has no stored file data. "
                "Re-upload the business card image — the current asset was seeded "
                "before the file_data column existed and lacks the DB fallback required "
                "for the worker to send it."
            )

    async def _resolve_test_numbers(self) -> list[str]:
        row = await self.repo.get(SETTING_AI_TEST_NUMBERS, scope="global")
        if row is None or not isinstance(row.value, dict):
            return list(AI_TEST_NUMBERS_DEFAULT["numbers"])
        numbers = row.value.get("numbers", [])
        if not isinstance(numbers, list):
            return list(AI_TEST_NUMBERS_DEFAULT["numbers"])
        return [str(n) for n in numbers]

    async def get_ai_settings(self) -> AISettingsResponse:
        business_card_media_id = await self._resolve_str(
            SETTING_AI_BUSINESS_CARD_MEDIA_ID, "media_asset_id"
        )
        return AISettingsResponse(
            kill_switch=await self._resolve_bool(SETTING_AI_KILL_SWITCH),
            auto_send_enabled=await self._resolve_bool(
                SETTING_AI_AUTO_SEND_ENABLED
            ),
            test_numbers=await self._resolve_test_numbers(),
            tag_suggestions_enabled=await self._resolve_bool(
                SETTING_AI_TAG_SUGGESTIONS_ENABLED
            ),
            response_generation_enabled=await self._resolve_bool(
                SETTING_AI_RESPONSE_GENERATION_ENABLED
            ),
            business_card_media_id=business_card_media_id,
        )

    async def update_ai_settings(
        self, payload: AISettingsUpdateRequest, *, actor_id: uuid.UUID
    ) -> AISettingsResponse:
        bool_fields = {
            "kill_switch": SETTING_AI_KILL_SWITCH,
            "auto_send_enabled": SETTING_AI_AUTO_SEND_ENABLED,
            "tag_suggestions_enabled": SETTING_AI_TAG_SUGGESTIONS_ENABLED,
            "response_generation_enabled": SETTING_AI_RESPONSE_GENERATION_ENABLED,
        }
        for field_name, key in bool_fields.items():
            new_val = getattr(payload, field_name)
            if new_val is None:
                continue
            await self.set_setting(
                key, {"enabled": new_val}, actor_id=actor_id
            )
        if payload.test_numbers is not None:
            cleaned = [str(n).strip() for n in payload.test_numbers if str(n).strip()]
            if len(cleaned) > 5:
                raise ValueError("Maximum 5 test numbers allowed.")
            await self.set_setting(
                SETTING_AI_TEST_NUMBERS,
                {"numbers": cleaned},
                actor_id=actor_id,
            )
        if payload.business_card_media_id is not None:
            await self._validate_business_card_media(payload.business_card_media_id)
            await self.set_setting(
                SETTING_AI_BUSINESS_CARD_MEDIA_ID,
                {"media_asset_id": payload.business_card_media_id},
                actor_id=actor_id,
            )
        return await self.get_ai_settings()

    async def _resolve_json(self, key: str) -> dict:
        row = await self.repo.get(key, scope="global")
        if row is None or not isinstance(row.value, dict):
            return dict(OPERATIONAL_SETTING_DEFAULTS[key])
        merged = dict(OPERATIONAL_SETTING_DEFAULTS[key])
        merged.update(row.value)
        return merged

    async def get_operational_settings(self) -> OperationalSettingsResponse:
        # `_resolve_json` returns plain dicts; Pydantic coerces them into the
        # nested sub-models. Use `model_validate` so mypy sees the input as
        # `Any` (the constructor's nested fields are typed as the models).
        return OperationalSettingsResponse.model_validate(
            {
                "read_only_mode": await self._resolve_json(
                    SETTING_OPS_READ_ONLY_MODE
                ),
                "timezone": await self._resolve_json(SETTING_OPS_TIMEZONE),
                "business_hours": await self._resolve_json(
                    SETTING_OPS_BUSINESS_HOURS
                ),
                "campaign_daily_cap": await self._resolve_json(
                    SETTING_OPS_CAMPAIGN_DAILY_CAP
                ),
                "delivery_failure_retry": await self._resolve_json(
                    SETTING_OPS_DELIVERY_FAILURE_RETRY
                ),
            }
        )

    async def update_operational_settings(
        self,
        payload: OperationalSettingsUpdateRequest,
        *,
        actor_id: uuid.UUID,
    ) -> OperationalSettingsResponse:
        field_to_key = {
            "read_only_mode": SETTING_OPS_READ_ONLY_MODE,
            "timezone": SETTING_OPS_TIMEZONE,
            "business_hours": SETTING_OPS_BUSINESS_HOURS,
            "campaign_daily_cap": SETTING_OPS_CAMPAIGN_DAILY_CAP,
            "delivery_failure_retry": SETTING_OPS_DELIVERY_FAILURE_RETRY,
        }
        for field_name, key in field_to_key.items():
            group = getattr(payload, field_name)
            if group is None:
                continue
            await self.set_setting(
                key, group.model_dump(), actor_id=actor_id
            )
        return await self.get_operational_settings()


class ChatExportService:
    """Build a JSONL export of all conversations with messages.

    Async; **returns raw bytes** (no DB writes, so no commit needed).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build_export(self) -> bytes:
        """Return the full JSONL export as UTF-8 bytes."""
        import json

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.modules.conversations.models import Conversation

        stmt = (
            select(Conversation)
            .options(
                selectinload(Conversation.contact),
                selectinload(Conversation.messages),
            )
            .order_by(Conversation.created_at)
        )
        result = await self.session.execute(stmt)
        conversations = result.unique().scalars().all()

        lines: list[str] = []
        for conv in conversations:
            if not conv.messages:
                continue
            lines.append(json.dumps(self._format(conv), ensure_ascii=False))

        if not lines:
            return b"# No conversations with messages found.\n"
        return ("\n".join(lines) + "\n").encode("utf-8")

    @staticmethod
    def _format(conv: Conversation) -> dict:
        return {
            "conversation_id": str(conv.id),
            "contact": {
                "name": conv.contact.name if conv.contact else None,
                "phone": conv.contact.phone if conv.contact else None,
            },
            "state": conv.state,
            "ai_enabled": conv.ai_enabled,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "last_message_at": (
                conv.last_message_at.isoformat() if conv.last_message_at else None
            ),
            "messages": [
                {
                    "direction": m.direction,
                    "sender_type": m.sender_type,
                    "content": m.content,
                    "msg_type": m.msg_type,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "delivery_status": m.delivery_status,
                }
                for m in conv.messages
            ],
        }
