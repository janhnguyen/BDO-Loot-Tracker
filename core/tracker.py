import threading
import time

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

# Scroll detection: maximum per-pixel mean diff (0-255) to accept a shift match.
_SCROLL_MATCH_THRESHOLD = 25
# Maximum scroll to check in pixels (full-res). Covers many simultaneous drops.
_MAX_SCROLL_PX = 300


class Tracker:
    def __init__(self, on_event, on_ocr, on_ocr_frame=None):
        self._running = False
        self._thread = None
        self._zone = "Unknown"

        self._on_event = on_event
        self._on_ocr = on_ocr
        self._on_ocr_frame = on_ocr_frame

        self._tracking_window_size: int = max(_WINDOW_MIN, min(_WINDOW_MAX, TRACKING_WINDOW_SIZE))
        self._suppress_events_until = 0.0
        self._paused = False
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

    def is_paused(self):
        return self._paused

    def start(self):
        if self._running:
            return
        self._paused = False
        self._suppress_events_until = time.monotonic() + SESSION_RESET_DELAY_SECONDS
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False
        # Re-suppress briefly so the settled frame after un-pause isn't counted.
        self._suppress_events_until = time.monotonic() + SESSION_RESET_DELAY_SECONDS

    def stop(self):
        self._paused = False
        self._running = False

    def get_session_reset_delay(self) -> float:
        return SESSION_RESET_DELAY_SECONDS

    @staticmethod
    def _detect_scroll_shift(prev: Image.Image, curr: Image.Image) -> int:
        """
        Find how many pixels curr has scrolled up relative to prev.

        Works at 1/8 scale on the preprocessed (grayscale) frames.
        First computes the s=0 baseline diff (direct frame comparison).
        If the frames are nearly identical there is no scroll → return 0.
        Otherwise tries each candidate upward shift s; accepts the best only
        if its overlap score is both below the noise threshold AND meaningfully
        better than the s=0 baseline (i.e. the shift actually explains the diff).
        """
        w, h = prev.size
        tw, th = max(4, w // 8), max(4, h // 8)
        max_s = min(th // 2, max(1, _MAX_SCROLL_PX // 8))

        a = list(prev.resize((tw, th), Image.BOX).getdata())
        b = list(curr.resize((tw, th), Image.BOX).getdata())
        n_total = tw * th

        # Baseline: direct frame comparison (s=0). If nearly identical, no scroll.
        score_0 = sum(abs(av - bv) for av, bv in zip(a, b)) / n_total
        if score_0 < 2:
            return 0

        best_s, best_score = 0, float('inf')
        for s in range(1, max_s + 1):
            overlap = th - s
            n = overlap * tw
            a_part = a[s * tw : (s + overlap) * tw]
            b_part = b[:n]
            score = sum(abs(av - bv) for av, bv in zip(a_part, b_part)) / n
            if score < best_score:
                best_score = score
                best_s = s

        # Reject if the shift doesn't explain the change better than no shift.
        if best_score > _SCROLL_MATCH_THRESHOLD or best_score >= score_0:
            return 0
        return best_s * 8

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
        Isolate bright text (white, orange, gold, yellow) against the dark
        acquisition log background. Uses peak channel so coloured text is kept.
        """
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
        prev_processed: Image.Image | None = None

        while self._running:
            if self._paused:
                time.sleep(0.1)
                continue
            try:
                img = self._capture()
                processed_img = self._preprocess_for_ocr(img)

                if self._on_ocr_frame:
                    self._on_ocr_frame(img, processed_img)

                if prev_processed is None:
                    prev_processed = processed_img
                    time.sleep(POLL_INTERVAL)
                    continue

                shift_px = self._detect_scroll_shift(prev_processed, processed_img)

                # Always OCR the full frame for the raw debug log.
                full_text = pytesseract.image_to_string(processed_img, config="--psm 6")
                if full_text.strip():
                    self._on_ocr(full_text)

                # Require the new strip to be at least one text-line tall (~20px).
                if shift_px >= 20 and time.monotonic() >= self._suppress_events_until:
                    # Crop only the newly scrolled-in content at the bottom.
                    pw, ph = processed_img.size
                    new_strip = processed_img.crop((0, ph - shift_px, pw, ph))
                    text = pytesseract.image_to_string(new_strip, config="--psm 6")

                    drops = parse_loot(text)
                    if drops:
                        self._current_batch_overrides = resolve_batch_zone_overrides(
                            [d[0] for d in drops]
                        )
                        for item_name, qty in drops:
                            self._on_event(LootEvent(
                                item_name=item_name,
                                quantity=qty,
                                zone=self._zone,
                                raw_text=text[:500],
                                character=CHARACTER_NAME,
                            ))

                prev_processed = processed_img

            except Exception as e:
                print("Error:", e)

            time.sleep(POLL_INTERVAL)
