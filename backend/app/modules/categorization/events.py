"""Categorization domain events published to the event bus."""


class TagEvents:
    APPROVED = "tag.approved"
    REJECTED = "tag.rejected"
    SUGGESTED = "tag.suggested"
