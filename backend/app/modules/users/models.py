"""Re-export of the User model — no new tables for this module."""

from app.modules.auth.models import User

__all__ = ["User"]
