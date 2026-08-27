"""Unit tests for campaign category CRUD request schemas (Settings epic piece 5)."""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.campaigns.schemas import (
    CampaignCategoryCreateRequest,
    CampaignCategoryUpdateRequest,
    CampaignCreateRequest,
)


def test_color_accepts_hex():
    obj = CampaignCategoryCreateRequest(name="promo", color="#00ff7f")
    assert obj.color == "#00ff7f"


def test_color_accepts_null():
    obj = CampaignCategoryCreateRequest(name="promo", color=None)
    assert obj.color is None


def test_color_rejects_bad_hex():
    for bad in ("00ff7f", "#ZZZZZZ", "#fff"):
        with pytest.raises(ValidationError):
            CampaignCategoryCreateRequest(name="promo", color=bad)


def test_create_rejects_unknown_field():
    with pytest.raises(ValidationError):
        CampaignCategoryCreateRequest(name="promo", foo="bar")  # type: ignore[call-arg]


def test_create_name_required_and_trimmed():
    with pytest.raises(ValidationError):
        CampaignCategoryCreateRequest(name="   ")
    obj = CampaignCategoryCreateRequest(name="  Holiday  ")
    assert obj.name == "Holiday"


def test_update_allows_empty_body_object():
    obj = CampaignCategoryUpdateRequest()
    assert obj.model_dump(exclude_unset=True) == {}


def test_update_color_validator_also_applies():
    with pytest.raises(ValidationError):
        CampaignCategoryUpdateRequest(color="not-a-hex")
    obj = CampaignCategoryUpdateRequest(color="#abcdef")
    assert obj.color == "#abcdef"


def test_campaign_create_accepts_category_id():
    cat = uuid.uuid4()
    obj = CampaignCreateRequest(
        template_id=uuid.uuid4(),
        name="Welcome Blast",
        category_id=cat,
    )
    assert obj.category_id == cat


def test_campaign_create_defaults_category_id_none():
    obj = CampaignCreateRequest(template_id=uuid.uuid4(), name="x")
    assert obj.category_id is None
