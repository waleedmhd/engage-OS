"""Operational config: typed view + pure timezone math (piece 2).

No Redis, no Celery here — pure helpers take an explicit aware ``now_utc``
so they are deterministic under test. The sync DB read mirrors the
``select(AppSetting)`` pattern used by campaigns/tasks.py and reuses the
caller's session (no extra connection).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, select
from sqlalchemy.orm import Session as SyncSession

from app.modules.settings.constants import (
    OPERATIONAL_SETTING_DEFAULTS,
    OPS_CAMPAIGN_DAILY_CAP_DEFAULT_LIMIT,
    OPS_DEFAULT_TIMEZONE,
    SETTING_OPS_BUSINESS_HOURS,
    SETTING_OPS_CAMPAIGN_DAILY_CAP,
    SETTING_OPS_TIMEZONE,
)
from app.modules.settings.models import AppSetting


@dataclass(frozen=True)
class BusinessHours:
    enabled: bool
    start: time
    end: time


@dataclass(frozen=True)
class DailyCap:
    enabled: bool
    limit: int


@dataclass(frozen=True)
class OperationalConfig:
    tz: ZoneInfo
    business_hours: BusinessHours
    cap: DailyCap


def _parse_hhmm(raw: str, fallback: time) -> time:
    try:
        h, m = raw.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return fallback


def _read_value_sync(session: SyncSession, key: str) -> dict | None:
    stmt = select(AppSetting).where(
        and_(AppSetting.key == key, AppSetting.scope == "global")
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict):
        return None
    return row.value


def read_operational_config_sync(session: SyncSession) -> OperationalConfig:
    """Resolve the effective operational config. Missing/malformed rows
    fall back to OPERATIONAL_SETTING_DEFAULTS.

    ops.read_only_mode is intentionally not read here — it is consumed by
    the HTTP layer (app.core.middleware), not the campaign Celery path.
    """
    tz_val = _read_value_sync(session, SETTING_OPS_TIMEZONE) or {}
    tz_name = tz_val.get("tz", OPS_DEFAULT_TIMEZONE)
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(OPS_DEFAULT_TIMEZONE)

    bh_default = OPERATIONAL_SETTING_DEFAULTS[SETTING_OPS_BUSINESS_HOURS]
    bh = _read_value_sync(session, SETTING_OPS_BUSINESS_HOURS) or bh_default
    business_hours = BusinessHours(
        enabled=bool(bh.get("enabled", bh_default["enabled"])),
        start=_parse_hhmm(bh.get("start", bh_default["start"]), time(9, 0)),
        end=_parse_hhmm(bh.get("end", bh_default["end"]), time(18, 0)),
    )

    cap_default = OPERATIONAL_SETTING_DEFAULTS[SETTING_OPS_CAMPAIGN_DAILY_CAP]
    cap_val = _read_value_sync(session, SETTING_OPS_CAMPAIGN_DAILY_CAP) or cap_default
    try:
        limit = int(cap_val.get("limit", OPS_CAMPAIGN_DAILY_CAP_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = OPS_CAMPAIGN_DAILY_CAP_DEFAULT_LIMIT
    cap = DailyCap(
        enabled=bool(cap_val.get("enabled", cap_default["enabled"])),
        limit=limit,
    )
    return OperationalConfig(tz=tz, business_hours=business_hours, cap=cap)


def _local_now(cfg: OperationalConfig, now_utc: datetime) -> datetime:
    return now_utc.astimezone(cfg.tz)


def is_within_business_hours(cfg: OperationalConfig, now_utc: datetime) -> bool:
    if not cfg.business_hours.enabled:
        return True
    local_t = _local_now(cfg, now_utc).timetz().replace(tzinfo=None)
    return cfg.business_hours.start <= local_t < cfg.business_hours.end


def seconds_until_window_open(cfg: OperationalConfig, now_utc: datetime) -> int:
    """Seconds until the next time the window opens. Assumes the caller
    already determined we are outside the window."""
    local = _local_now(cfg, now_utc)
    open_today = local.replace(
        hour=cfg.business_hours.start.hour,
        minute=cfg.business_hours.start.minute,
        second=0,
        microsecond=0,
    )
    target = open_today if local < open_today else open_today + timedelta(days=1)
    return max(1, int((target - local).total_seconds()))


def seconds_until_local_midnight(cfg: OperationalConfig, now_utc: datetime) -> int:
    local = _local_now(cfg, now_utc)
    next_midnight = (local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((next_midnight - local).total_seconds()))


def daily_counter_key(cfg: OperationalConfig, now_utc: datetime) -> str:
    local_date = _local_now(cfg, now_utc).strftime("%Y-%m-%d")
    return f"campaign:daily_sent:{local_date}"
