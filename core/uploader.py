import queue
import threading
import time

import requests
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import SUPABASE_URL, SUPABASE_KEY

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

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

UPLOAD_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.75

_queue = queue.Queue()

def _uploader_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def upload_event(event: LootEvent):
    if not _uploader_enabled():
        print("Uploader disabled: SUPABASE_URL/SUPABASE_KEY not configured.")
        return False

    payload = {
        "created_at": event.timestamp.isoformat(),
        "character": event.character,
        "zone": event.zone,
        "item_name": event.item_name,
        "quantity": event.quantity,
        "raw_text": event.raw_text,
        "time": event.time,
        "avg_hour": event.avg_hour,
    }

    last_error = None
    for attempt in range(1, UPLOAD_RETRIES + 1):
        try:
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/loot_events",
                headers=HEADERS,
                json=payload,
                timeout=5,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            last_error = exc
            if attempt < UPLOAD_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    print(f"Failed to upload loot event after {UPLOAD_RETRIES} attempts: {last_error}")
    return False

def _worker():
    while True:
        event = _queue.get()
        try:
            if event is None:
                return
            upload_event(event)
        finally:
            _queue.task_done()

threading.Thread(target=_worker, daemon=True).start()

def queue_upload(event):
    _queue.put(event)
