"""Cross-stream Pydantic / typing contracts.

Stream C owns the discovery + messaging trio in this file: `Listing`,
`MessageId`, `Reply`. Stream B appends `Job`, `ApprovalCard`, `Message`,
`Case`, `Skill`, `IntegrationAccount` on its branch — keep imports of this
module tolerant of missing symbols at import time.
"""

from typing import NewType, Optional

from pydantic import BaseModel, Field

MessageId = NewType("MessageId", str)


class Listing(BaseModel):
    marketplace: str  # 'fb' | 'nextdoor' | 'offerup' | 'craigslist'
    listing_id: str  # provider's id
    title: Optional[str] = None
    description: Optional[str] = None
    price_cents: Optional[int] = None
    currency: str = "USD"
    url: Optional[str] = None
    raw: dict = Field(default_factory=dict)  # full provider response


class Reply(BaseModel):
    message_id: MessageId
    listing_id: str
    sender: str  # 'seller' | 'system'
    text: str
    received_at: float  # unix ts
