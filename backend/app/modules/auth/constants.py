"""Auth constants — roles per DSD §6.1."""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    AGENT = "agent"
