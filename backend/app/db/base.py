"""SQLAlchemy declarative base with Alembic-friendly naming convention."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"


def import_all_models() -> None:
    """Import every module's models so SQLAlchemy registers them.

    Called by Alembic env.py and the Celery app at startup. Auto-discovers
    modules by scanning ``app/modules/`` for directories containing a
    ``models.py`` file. Also handles ``memory_models.py`` (contacts module).

    Previously hardcoded (22 explicit imports); auto-discovered as of
    2026-07-22. Restore the explicit list if auto-discovery ever breaks.
    """
    for entry in sorted(os.listdir(_MODULES_DIR)):
        module_path = _MODULES_DIR / entry
        if not module_path.is_dir() or entry.startswith("_") or entry.startswith("."):
            continue
        models_file = module_path / "models.py"
        if models_file.is_file():
            importlib.import_module(f"app.modules.{entry}.models")
        memory_file = module_path / "memory_models.py"
        if memory_file.is_file():
            importlib.import_module(f"app.modules.{entry}.memory_models")
