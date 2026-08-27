"""Helpers for emitting DB-level CHECK constraints from Python StrEnums.

Usage:

    from my_module.constants import MyStatusEnum
    from app.db.constraints import enum_check

    __table_args__ = (enum_check("status", MyStatusEnum, "status_valid"),)
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import CheckConstraint


def enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name)
