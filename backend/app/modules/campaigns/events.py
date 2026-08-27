"""Campaign domain events published to the event bus."""


class CampaignEvents:
    COMPLETED = "campaign.completed"
    FAILED = "campaign.failed"
    LAUNCHED = "campaign.launched"
