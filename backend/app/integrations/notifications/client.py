"""Operator notifications (Slack, email, etc.) — placeholder for future use."""


class NotificationsClient:
    async def notify(self, channel: str, message: str, **context) -> None:
        raise NotImplementedError("notifications integration is out of scope for Phase 0")
