"""AppSetting key/value table.

Not in DSD §5; supports runtime feature flags (maintenance mode, daily send
caps) without redeploy. Scope is `global` by default; `user:<uuid>` or
`tenant:<uuid>` patterns can be added later.
"""

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class AppSetting(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        Index("ix_app_settings_scope_key", "scope", "key", unique=True),
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    scope: Mapped[str] = mapped_column(String(32), nullable=False, server_default="global")
