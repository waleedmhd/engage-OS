"""ID generation helpers."""

import uuid


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False
