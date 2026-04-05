import threading
import time
from collections import Counter, deque

import mss
import pytesseract
from PIL import Image, ImageFilter

from .parser import parse_loot, resolve_batch_zone_overrides
from .uploader import LootEvent
from .config import (
    POLL_INTERVAL,
    CHARACTER_NAME,
    REGION_LEFT_PCT,
    REGION_TOP_PCT,
    REGION_RIGHT_PCT,
    REGION_BOTTOM_PCT,
    SESSION_RESET_DELAY_SECONDS,
    TRACKING_WINDOW_SIZE,
)

_WINDOW_MIN = 15
_WINDOW_MAX = 30

class Tracker:
    def __init__(self, on_event, on_ocr):
        self._running = False
        self._thread = None
        self._zone = "Unknown"

        self._on_event = on_event
        self._on_ocr = on_ocr

        self._tracking_window_size: int = max(_WINDOW_MIN, min(_WINDOW_MAX, TRACKING_WINDOW_SIZE))

        # Tracks the visible FIFO window of loot entries (top -> bottom).
        self._prev_window: list[tuple[str, int]] = []
        self._suppress_events_until = 0.0
        self._seen_windows = deque(maxlen=200)
        self._current_batch_overrides: dict[str, str] = {}

    def set_zone(self, zone):
        self._zone = zone

    def get_zone(self):
        return self._zone

    def get_batch_zone_override(self, item_name: str) -> str | None:
        return self._current_batch_overrides.get(item_name)

    def get_tracking_window_size(self) -> int:
        return self._tracking_window_size

    def set_tracking_window_size(self, n: int):
        self._tracking_window_size = max(_WINDOW_MIN, min(_WINDOW_MAX, int(n)))

    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return
        # Start a new tracking session with a short warmup period to let the
        # OCR settle on the existing on-screen log before counting new drops.
        self._prev_window = []
        self._suppress_events_until = time.monotonic() + SESSION_RESET_DELAY_SECONDS
        self._seen_windows.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_session_reset_delay(self) -> float:
        return SESSION_RESET_DELAY_SECONDS

    @staticmethod
    def _detect_new_entries(prev_window: list[tuple[str, int]], curr_window: list[tuple[str, int]]) -> list[tuple[str, int]]:
        """
        Compare two FIFO snapshots and return only entries newly appended to the
        bottom of the current window.
        """
        max_overlap = min(len(prev_window), len(curr_window))
        overlap = 0
        for k in range(max_overlap, 0, -1):
            if prev_window[-k:] == curr_window[:k]:
                overlap = k
                break
        if overlap > 0 or not prev_window:
            return curr_window[overlap:]

        # Fallback for OCR jitter: if no reliable FIFO overlap is found, avoid
        # replaying the entire visible window. Emit only occurrences that are
        # above the previous frame's item multiset.
        prev_counts = Counter(prev_window)
        new_entries: list[tuple[str, int]] = []
        for entry in curr_window:
            if prev_counts[entry] > 0:
                prev_counts[entry] -= 1
            else:
                new_entries.append(entry)
        return new_entries

    def _capture(self):
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            w, h = monitor["width"], monitor["height"]

            region = {
                "left": int(w * REGION_LEFT_PCT),
                "top": int(h * REGION_TOP_PCT),
                "width": int(w * (REGION_RIGHT_PCT - REGION_LEFT_PCT)),
                "height": int(h * (REGION_BOTTOM_PCT - REGION_TOP_PCT)),
            }

            img = sct.grab(region)

        raw = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
        return raw.resize((raw.width * 2, raw.height * 2), Image.LANCZOS)

    def _preprocess_for_ocr(self, pil_img: Image.Image) -> Image.Image:
        """
        Isolate white text by requiring pixels to be both bright AND unsaturated
        (R ≈ G ≈ B).  Bright-but-coloured pixels (grass, path) are rejected.
        """
        # Capture any text (white, orange, gold, yellow) against the dark
        # acquisition log background. Using peak channel instead of requiring
        # all channels to be bright, so coloured text isn't filtered out.
        BRIGHT_MIN = 135

        rgb  = pil_img.convert("RGB")
        data = rgb.load()
        w, h = rgb.size

        out = Image.new("L", (w, h), 255)
        pix = out.load()

        for y in range(h):
            for x in range(w):
                r, g, b = data[x, y]
                if max(r, g, b) > BRIGHT_MIN:
                    pix[x, y] = 0
        out = out.filter(ImageFilter.MinFilter(3))
        return out

    def _loop(self):
        while self._running:
            try:
                img = self._capture()
                processed_img = self._preprocess_for_ocr(img)
                text = pytesseract.image_to_string(processed_img, config="--psm 6")

                if text.strip():
                    self._on_ocr(text)

                drops = parse_loot(text)

                # OCR lines are top->bottom. Keep only the newest entries from
                # the visible FIFO region to reduce duplicate recounts.
                curr_window = drops[-self._tracking_window_size:]
                window_key = tuple(curr_window)

                if time.monotonic() >= self._suppress_events_until:
                    if window_key and window_key in self._seen_windows:
                        new_entries = []
                    else:
                        new_entries = self._detect_new_entries(self._prev_window, curr_window)

                    self._current_batch_overrides = resolve_batch_zone_overrides(
                        [k[0] for k in new_entries]
                    )

                    for key in new_entries:
                        self._on_event(LootEvent(
                            item_name=key[0],
                            quantity=key[1],
                            zone=self._zone,
                            raw_text=text[:500],
                            character=CHARACTER_NAME,
                        ))

                if window_key:
                    self._seen_windows.append(window_key)
                    self._prev_window = curr_window

            except Exception as e:
                print("Error:", e)

            time.sleep(POLL_INTERVAL)