"""Schema-level validation for CampaignCreateRequest.

Exercises the cross-field validators that gate scheduled / recurring types.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.modules.campaigns.schemas import (
    AudienceFilter,
    CampaignCreateRequest,
)


def _base_payload(**overrides):
    base = {
        "template_id": uuid.uuid4(),
        "name": "Test campaign",
        "type": "immediate",
        "audience_filter": AudienceFilter().model_dump(),
    }
    base.update(overrides)
    return base


def test_immediate_campaign_does_not_require_schedule() -> None:
    req = CampaignCreateRequest(**_base_payload())
    assert req.type == "immediate"


def test_scheduled_requires_scheduled_at() -> None:
    with pytest.raises(ValidationError):
        CampaignCreateRequest(**_base_payload(type="scheduled"))


def test_scheduled_at_in_past_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(ValidationError):
        CampaignCreateRequest(
            **_base_payload(type="scheduled", scheduled_at=past)
        )


def test_scheduled_at_in_future_is_accepted() -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    req = CampaignCreateRequest(
        **_base_payload(type="scheduled", scheduled_at=future)
    )
    assert req.scheduled_at == future


def test_recurring_requires_cron_expression() -> None:
    with pytest.raises(ValidationError):
        CampaignCreateRequest(**_base_payload(type="recurring"))


def test_recurring_rejects_invalid_cron() -> None:
    with pytest.raises(ValidationError):
        CampaignCreateRequest(
            **_base_payload(type="recurring", cron_expression="not a cron")
        )


def test_recurring_accepts_valid_cron() -> None:
    req = CampaignCreateRequest(
        **_base_payload(type="recurring", cron_expression="0 9 * * MON")
    )
    assert req.cron_expression == "0 9 * * MON"


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CampaignCreateRequest(**_base_payload(type="weekly"))


def test_audience_filter_accepts_contact_ids() -> None:
    cid = uuid.uuid4()
    af = AudienceFilter(contact_ids=[cid])
    assert af.contact_ids == [cid]


def test_audience_filter_contact_ids_defaults_to_empty() -> None:
    af = AudienceFilter()
    assert af.contact_ids == []


def test_audience_filter_rejects_invalid_contact_ids() -> None:
    with pytest.raises(ValidationError):
        AudienceFilter(contact_ids=["not-a-uuid"])


def test_rate_limit_bounds() -> None:
    with pytest.raises(ValidationError):
        CampaignCreateRequest(**_base_payload(rate_limit_per_second=0))
    with pytest.raises(ValidationError):
        CampaignCreateRequest(**_base_payload(rate_limit_per_second=10_000))
    req = CampaignCreateRequest(**_base_payload(rate_limit_per_second=25))
    assert req.rate_limit_per_second == 25
