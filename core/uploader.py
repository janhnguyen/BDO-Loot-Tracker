from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class LootEvent:
    item_name: str
    quantity: int
    zone: str
    raw_text: str
    character: str
    time: float = 0.0
    avg_hour: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
