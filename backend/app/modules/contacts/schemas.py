"""Contact request/response schemas (DSD §6.2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.modules.categorization.schemas import TagResponse
from app.modules.contacts.constants import ContactStatus


def _split_csv(raw: str | None) -> list[str]:
    """Split a comma-separated string, discarding empty segments and whitespace."""
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _split_csv_uuids(raw: str | None) -> list[uuid.UUID]:
    """Split comma-separated UUID strings, silently dropping malformed ones."""
    ids: list[uuid.UUID] = []
    for s in _split_csv(raw):
        try:
            ids.append(uuid.UUID(s))
        except ValueError:
            pass
    return ids


class ContactCreateRequest(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32)
    name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    status: str | None = None
    notes: str | None = None
    information: str | None = None
    assigned_agent_id: uuid.UUID | None = None
    ai_assigned: bool = False
    estimated_ltv: Decimal | None = None

    @field_validator("phone")
    @classmethod
    def _canonicalize_phone(cls, v: str) -> str:
        """Store the canonical digits-only (wa_id) form so the contact matches
        Meta's bare-wa_id inbound `from` and is never re-created as a duplicate
        on the customer's first reply. See app.modules.contacts.phone."""
        from app.modules.contacts.phone import canonicalize_phone

        canonical = canonicalize_phone(v)
        if not canonical:
            raise ValueError("phone must contain at least one digit")
        return canonical

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {e.value for e in ContactStatus}
        if v not in valid:
            raise ValueError(f"status must be one of {sorted(valid)}")
        return v


class ContactUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    information: str | None = None
    status: str | None = None
    assigned_agent_id: uuid.UUID | None = None
    ai_assigned: bool | None = None
    estimated_ltv: Decimal | None = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {e.value for e in ContactStatus}
        if v not in valid:
            raise ValueError(f"status must be one of {sorted(valid)}")
        return v


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    name: str | None = None
    company: str | None = None
    status: str
    notes: str | None = None
    information: str | None = None
    assigned_agent_id: uuid.UUID | None = None
    ai_assigned: bool = False
    revenue_attributed: Decimal
    estimated_ltv: Decimal | None = None
    last_interaction_at: datetime | None = None
    last_contacted_at: datetime | None = None
    last_inbound_at: datetime | None = None
    conversation_count: int
    created_at: datetime
    updated_at: datetime
    tags: list[TagResponse] = []

    @field_serializer("phone")
    @classmethod
    def _format_phone(cls, phone: str) -> str:
        from app.modules.contacts.phone import format_phone_for_display

        return format_phone_for_display(phone)

    @classmethod
    def from_orm_with_tags(cls, contact) -> ContactResponse:
        """Build a response with resolved tag chips from an ORM Contact whose
        `contact_tags.tag` relationship has been eager-loaded.

        Only call this when the relationship is loaded (the list endpoint) —
        accessing `contact.contact_tags` on a lazily-loaded async object would
        raise. The plain `model_validate(contact)` path leaves `tags` empty.
        """
        obj = cls.model_validate(contact)
        obj.tags = [
            TagResponse.model_validate(ct.tag)
            for ct in contact.contact_tags
            if ct.tag is not None
        ]
        return obj


class ContactImportRowError(BaseModel):
    """Per-row error detail returned in the import receipt."""

    row: int = Field(..., description="1-based row number (header is row 1)")
    phone: str | None = None
    error: str


class ContactImportReceipt(BaseModel):
    """Result of a CSV import.

    Counts are mutually exclusive within a row: a single CSV row contributes
    to exactly one of created / updated / skipped / errors.
    """

    total_rows: int = Field(..., description="Data rows seen (excludes header)")
    created: int
    updated: int
    skipped: int = Field(..., description="Rows ignored due to malformed/missing phone")
    errors: list[ContactImportRowError] = Field(
        default_factory=list,
        description="Per-row failures, capped at 100 entries",
    )


class ContactUpsertRequest(BaseModel):
    """Minimal upsert-by-phone for external services (e.g. group listener).

    ``information`` is APPENDED to the existing value so repeated ingestion
    accumulates context rather than overwriting.
    """

    phone: str = Field(..., min_length=4, max_length=32)
    name: str | None = Field(default=None, max_length=200)
    information: str | None = None

    @field_validator("phone")
    @classmethod
    def _canonicalize_phone(cls, v: str) -> str:
        from app.modules.contacts.phone import canonicalize_phone

        canonical = canonicalize_phone(v)
        if not canonical:
            raise ValueError("phone must contain at least one digit")
        return canonical


class ContactListFilters(BaseModel):
    """Filters accepted on GET /contacts. Pydantic parses query params via Depends().

    Multi-value fields (status, tag_id) accept comma-separated
    strings, e.g. ``?status=active,inactive``.
    """

    q: str | None = Field(default=None, description="Search across name/phone/company")
    status: str | None = Field(
        default=None,
        description="Comma-separated status values, e.g. active,inactive,follow_up",
    )
    assigned_agent_id: uuid.UUID | None = None
    tag_id: str | None = Field(
        default=None,
        description="Comma-separated tag UUIDs, e.g. <uuid1>,<uuid2>",
    )
    has_assigned_agent: bool | None = None
    ai_assigned: bool | None = None
    order_by: str = Field(
        default="-last_interaction_at",
        description="Sortable: last_interaction_at, created_at, name. Prefix '-' for desc.",
    )

    @property
    def status_list(self) -> list[str]:
        """Split comma-separated status into a list, stripping whitespace."""
        return _split_csv(self.status)

    @property
    def tag_id_list(self) -> list[uuid.UUID]:
        return _split_csv_uuids(self.tag_id)


# ============================================================ bulk actions

_BULK_IDS_MAX = 100


class BulkPatch(BaseModel):
    """Mutation payload for POST /contacts/bulk-update.

    All fields optional; at least one must be set. `assigned_agent_id` may
    be present only for admins — the router enforces that gate.
    """

    status: str | None = None
    assigned_agent_id: uuid.UUID | None = None
    ai_assigned: bool | None = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {e.value for e in ContactStatus}
        if v not in valid:
            raise ValueError(f"status must be one of {sorted(valid)}")
        return v

    def is_empty(self) -> bool:
        return self.model_dump(exclude_unset=True) == {}


class BulkUpdateRequest(BaseModel):
    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=_BULK_IDS_MAX)
    patch: BulkPatch

    @field_validator("ids")
    @classmethod
    def _dedup_ids(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        seen: set[uuid.UUID] = set()
        out: list[uuid.UUID] = []
        for cid in v:
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
        return out

    @field_validator("patch")
    @classmethod
    def _patch_not_empty(cls, v: BulkPatch) -> BulkPatch:
        if v.is_empty():
            raise ValueError("patch must contain at least one field")
        return v


class BulkDeleteRequest(BaseModel):
    ids: list[uuid.UUID] = Field(..., min_length=1, max_length=_BULK_IDS_MAX)

    @field_validator("ids")
    @classmethod
    def _dedup_ids(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        seen: set[uuid.UUID] = set()
        out: list[uuid.UUID] = []
        for cid in v:
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
        return out


class BulkActionFailure(BaseModel):
    id: uuid.UUID
    error: str


class BulkActionResponse(BaseModel):
    """Result of a bulk update or delete.

    `count` is the number of contacts successfully mutated.
    `failed` lists per-id errors (not_found, forbidden, conflict, etc.).
    """

    count: int
    failed: list[BulkActionFailure] = Field(default_factory=list)
