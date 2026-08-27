"""Re-export of common FastAPI dependencies used by module routers."""

from app.core.dependencies import (
    CurrentUser,
    CurrentUserClaims,
    CurrentUserDB,
    DbSession,
    SettingsDep,
    get_current_user,
    get_current_user_claims,
    get_current_user_db,
    get_db_session,
    get_settings_dep,
    require_role,
)

__all__ = [
    "CurrentUser",
    "CurrentUserClaims",
    "CurrentUserDB",
    "DbSession",
    "SettingsDep",
    "get_current_user",
    "get_current_user_claims",
    "get_current_user_db",
    "get_db_session",
    "get_settings_dep",
    "require_role",
]
