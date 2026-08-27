"""Template enums."""

from enum import StrEnum


class TemplateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISABLED = "disabled"


class TemplateCategory(StrEnum):
    MARKETING = "marketing"
    UTILITY = "utility"
    AUTHENTICATION = "authentication"


# Meta returns uppercase template states. Collapse the wider Meta vocabulary
# (PAUSED, IN_APPEAL, FLAGGED, PENDING_DELETION, DELETED, …) onto our 4-value
# enum: anything not explicitly APPROVED/PENDING/REJECTED is treated as
# DISABLED so the campaign approval gate stays conservative.
_META_STATUS_MAP: dict[str, TemplateStatus] = {
    "APPROVED": TemplateStatus.APPROVED,
    "PENDING": TemplateStatus.PENDING,
    "REJECTED": TemplateStatus.REJECTED,
}


def map_meta_status(meta_status: str | None) -> TemplateStatus:
    if not meta_status:
        return TemplateStatus.PENDING
    return _META_STATUS_MAP.get(meta_status.strip().upper(), TemplateStatus.DISABLED)
