"""Settings request/response schemas (P1.2).

Two surfaces:
  * Generic ``/settings/{key}`` get/put (SettingResponse / SettingUpdateRequest).
  * Typed admin dashboards: AI toggles (kill switch + auto-send) and
    operational toggles (read-only mode, timezone, business hours, campaign
    daily cap) — each backed by a validated nested model.
"""

import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class SettingResponse(BaseModel):
    key: str
    value: Any
    scope: str = "global"


class SettingUpdateRequest(BaseModel):
    value: Any


class AISettingsResponse(BaseModel):
    kill_switch: bool
    auto_send_enabled: bool
    test_numbers: list[str]
    tag_suggestions_enabled: bool
    response_generation_enabled: bool
    business_card_media_id: str | None = None


class AISettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kill_switch: bool | None = None
    auto_send_enabled: bool | None = None
    test_numbers: list[str] | None = None
    tag_suggestions_enabled: bool | None = None
    response_generation_enabled: bool | None = None
    business_card_media_id: str | None = None


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class ReadOnlyModeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class TimezoneModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tz: str

    @field_validator("tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {v!r}") from exc
        return v


class BusinessHoursModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not re.match(_HHMM, v):
            raise ValueError(f"time must be HH:MM 24h, got {v!r}")
        return v

    @model_validator(mode="after")
    def _end_after_start(self) -> "BusinessHoursModel":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class CampaignDailyCapModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    limit: int

    @field_validator("limit")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("limit must be a positive integer")
        return v


class DeliveryFailureRetryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class OperationalSettingsResponse(BaseModel):
    read_only_mode: ReadOnlyModeModel
    timezone: TimezoneModel
    business_hours: BusinessHoursModel
    campaign_daily_cap: CampaignDailyCapModel
    delivery_failure_retry: DeliveryFailureRetryModel


class OperationalSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_only_mode: ReadOnlyModeModel | None = None
    timezone: TimezoneModel | None = None
    business_hours: BusinessHoursModel | None = None
    campaign_daily_cap: CampaignDailyCapModel | None = None
    delivery_failure_retry: DeliveryFailureRetryModel | None = None
