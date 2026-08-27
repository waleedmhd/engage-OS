"""Contact-domain enums."""

from enum import StrEnum



class ContactStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    CONTACTED = "contacted"
    FOLLOW_UP = "follow_up"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
