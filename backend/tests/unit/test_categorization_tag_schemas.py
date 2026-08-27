"""Unit tests for tag CRUD request schemas (Settings epic piece 4)."""

import pytest
from pydantic import ValidationError

from app.modules.categorization.schemas import TagCreateRequest, TagUpdateRequest


def test_color_accepts_hex():
    obj = TagCreateRequest(name="vip", color="#00ff7f")
    assert obj.color == "#00ff7f"


def test_color_accepts_null():
    obj = TagCreateRequest(name="vip", color=None)
    assert obj.color is None


def test_color_rejects_bad_hex():
    with pytest.raises(ValidationError):
        TagCreateRequest(name="vip", color="00ff7f")
    with pytest.raises(ValidationError):
        TagCreateRequest(name="vip", color="#ZZZZZZ")
    with pytest.raises(ValidationError):
        TagCreateRequest(name="vip", color="#fff")


def test_create_rejects_unknown_field():
    with pytest.raises(ValidationError):
        TagCreateRequest(name="vip", foo="bar")  # type: ignore[call-arg]


def test_create_name_required_and_trimmed():
    with pytest.raises(ValidationError):
        TagCreateRequest(name="   ")
    obj = TagCreateRequest(name="  hot  ")
    assert obj.name == "hot"


def test_update_allows_empty_body_object():
    obj = TagUpdateRequest()
    assert obj.model_dump(exclude_unset=True) == {}


def test_update_color_validator_also_applies():
    with pytest.raises(ValidationError):
        TagUpdateRequest(color="not-a-hex")
    obj = TagUpdateRequest(color="#abcdef")
    assert obj.color == "#abcdef"
