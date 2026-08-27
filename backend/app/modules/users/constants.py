"""Stable error sentinels for the user-management surface.

Surfaced verbatim in 400 response bodies so tests and frontend clients
can match without coupling to wording.
"""

from __future__ import annotations

ERR_CANNOT_MODIFY_SELF = "cannot_modify_self"
ERR_LAST_ACTIVE_ADMIN = "last_active_admin"
ERR_NO_CHANGES = "no_changes"

AUDIT_ACTION_RESET_PASSWORD = "reset_password"
AUDIT_ENTITY_TYPE = "User"
PASSWORD_REDACTED = "***"
