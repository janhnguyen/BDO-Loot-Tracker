from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class LootEvent:
    item_name: str
    quantity: int
    zone: str
    character: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
