"""Messaging domain events published to the event bus."""


class MessageEvents:
    DELIVERED = "message.delivered"
    FAILED = "message.failed"
    READ = "message.read"
    RECEIVED = "message.received"
    SENT = "message.sent"
