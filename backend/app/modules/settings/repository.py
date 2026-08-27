"""Settings repository — key/value access for runtime feature flags."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.modules.settings.models import AppSetting


def get_bool_setting_sync(
    session: SyncSession,
    key: str,
    *,
    default: bool,
    scope: str = "global",
) -> bool:
    """Sync read of a {"enabled": bool} setting. Raises on DB error;
    callers in the message pipeline must wrap with a fail-open guard."""
    stmt = select(AppSetting).where(
        and_(AppSetting.key == key, AppSetting.scope == scope)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict) or "enabled" not in row.value:
        return default
    return bool(row.value["enabled"])


def get_numeric_setting_sync(
    session: SyncSession,
    key: str,
    *,
    default: float,
    scope: str = "global",
) -> float:
    """Sync read of a {"value": number} setting. Fail-open: return *default*
    when the setting is missing or the value can't be coerced to float."""
    stmt = select(AppSetting).where(
        and_(AppSetting.key == key, AppSetting.scope == scope)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict) or "value" not in row.value:
        return default
    try:
        return float(row.value["value"])
    except (ValueError, TypeError):
        return default


def get_test_numbers_sync(
    session: SyncSession,
    scope: str = "global",
) -> list[str]:
    """Sync read of ai.test_numbers → list of phone number strings.
    Returns an empty list when the setting is missing or malformed."""
    stmt = select(AppSetting).where(
        and_(AppSetting.key == "ai.test_numbers", AppSetting.scope == scope)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict):
        return []
    numbers = row.value.get("numbers", [])
    if not isinstance(numbers, list):
        return []
    return [str(n) for n in numbers]


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str, *, scope: str = "global") -> AppSetting | None:
        stmt = select(AppSetting).where(
            and_(AppSetting.key == key, AppSetting.scope == scope)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self, key: str, value: dict[str, Any], *, scope: str = "global"
    ) -> AppSetting:
        stmt = (
            pg_insert(AppSetting)
            .values(key=key, value=value, scope=scope)
            .on_conflict_do_update(
                index_elements=["scope", "key"], set_={"value": value}
            )
            .returning(AppSetting)
        )
        # populate_existing=True ensures the identity map is refreshed from the
        # RETURNING data even when get() loaded the same row earlier in this
        # session (otherwise the stale cached object would be returned).
        result = await self.session.execute(
            stmt, execution_options={"populate_existing": True}
        )
        row = result.scalar_one()
        await self.session.flush()
        return row

    async def list_all(self, *, scope: str | None = None) -> Sequence[AppSetting]:
        stmt = select(AppSetting)
        if scope:
            stmt = stmt.where(AppSetting.scope == scope)
        stmt = stmt.order_by(AppSetting.scope.asc(), AppSetting.key.asc())
        result = await self.session.execute(stmt)
        return result.scalars().all()
