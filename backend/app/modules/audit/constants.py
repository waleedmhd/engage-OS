"""Audit log enums (DSD §5 audit_logs, §9)."""

from enum import StrEnum


class ActorType(StrEnum):
    USER = "user"
    AI = "ai"
    SYSTEM = "system"
    WEBHOOK = "webhook"


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    APPROVE = "approve"
    REJECT = "reject"
    PAUSE_AI = "pause_ai"
    RESUME_AI = "resume_ai"
    ASSIGN = "assign"
    LAUNCH_CAMPAIGN = "launch_campaign"
