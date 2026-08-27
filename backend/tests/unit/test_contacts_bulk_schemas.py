"""Unit tests for bulk-action Pydantic schemas."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.contacts.schemas import (
    BulkDeleteRequest,
    BulkUpdateRequest,
)


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


class TestBulkUpdateRequest:
    def test_minimum_valid_payload(self):
        req = BulkUpdateRequest(ids=_ids(1), patch={"status": "active"})
        assert len(req.ids) == 1
        assert req.patch.status == "active"

    def test_empty_ids_rejected(self):
        with pytest.raises(ValidationError):
            BulkUpdateRequest(ids=[], patch={"status": "active"})

    def test_over_cap_rejected(self):
        with pytest.raises(ValidationError):
            BulkUpdateRequest(ids=_ids(101), patch={"status": "active"})

    def test_duplicate_ids_deduped(self):
        cid = uuid.uuid4()
        req = BulkUpdateRequest(ids=[cid, cid, cid], patch={"status": "active"})
        assert req.ids == [cid]

    def test_empty_patch_rejected(self):
        with pytest.raises(ValidationError):
            BulkUpdateRequest(ids=_ids(1), patch={})

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            BulkUpdateRequest(ids=_ids(1), patch={"status": "nope"})



class TestBulkDeleteRequest:
    def test_minimum_valid_payload(self):
        req = BulkDeleteRequest(ids=_ids(1))
        assert len(req.ids) == 1

    def test_empty_ids_rejected(self):
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=[])

    def test_over_cap_rejected(self):
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=_ids(101))
