import threading
import time

import mss
import numpy as np
import pytesseract
from PIL import Image, ImageFilter

from .parser import resolve_batch_zone_overrides
from .normalize import normalize_frame
from .alignment import align, is_glitch_frame, is_implausible_jump, GLITCH_MAX_SKIPS
from .fuzzy import MatchConfig
from .staging import LootStager
from .stability import StabilityGate, frame_difference
from .scroll_detect import estimate_scroll_px, expected_new_lines
from .diagnostics import FrameDiagnostics
from .metrics import TrackerMetrics
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
    LOOT_MIN_SIGHTINGS,
    NAME_FUZZY_THRESHOLD,
    ENABLE_STABILITY_GATE,
    STABILITY_DIFF_THRESHOLD,
    STABILITY_MIN_FRAMES,
    ENABLE_SCROLL_HINT,
    MAX_PLAUSIBLE_NEW,
    METRICS_LOG_INTERVAL_SECONDS,
    OCR_UPSCALE,
)

_WINDOW_MIN = 15
_WINDOW_MAX = 30

# Items must disappear by this many before treating the region as covered.
_COVERAGE_DROP_THRESHOLD = 5
# Downscaled grayscale frame height (px) used for stability + scroll detection.
_GRAY_HEIGHT = 60
# Mean abs pixel diff below which the frame is treated as unchanged (skip OCR).
_IDLE_DIFF_EPS = 0.5


class Tracker:
    def __init__(self, on_event, on_ocr, on_ocr_frame=None, on_strip_result=None,
                 on_diagnostics=None, on_missed=None, on_metrics=None):
        self._running = False
        self._thread = None
        self._zone = "Unknown"

        self._on_event = on_event
        self._on_ocr = on_ocr
        self._on_ocr_frame = on_ocr_frame
        self._on_strip_result = on_strip_result
        self._on_diagnostics = on_diagnostics
        self._on_missed = on_missed      # (text:str) -> log "{text}" to error + live log
        self._on_metrics = on_metrics    # (summary:str) -> periodic pipeline metrics

        self._metrics = TrackerMetrics()
        self._last_metrics_log = 0.0

        self._tracking_window_size: int = max(_WINDOW_MIN, min(_WINDOW_MAX, TRACKING_WINDOW_SIZE))
        self._suppress_events_until = 0.0
        self._paused = False
        self._current_batch_overrides: dict[str, str] = {}

        # --- Alignment / staging pipeline ---
        self._match_cfg = MatchConfig(name_threshold=NAME_FUZZY_THRESHOLD)
        self._stager = LootStager(min_sightings=LOOT_MIN_SIGHTINGS)
        self._gate = (
            StabilityGate(STABILITY_DIFF_THRESHOLD, STABILITY_MIN_FRAMES)
            if ENABLE_STABILITY_GATE else None
        )
        self._prev_lines: list | None = None    # last OCR'd frame (normalized); None = not set
        self._reseed_baseline: bool = False      # re-establish baseline on next frame (resume)
        self._prev_gray: np.ndarray | None = None
        self._visible_estimate: int = 0          # running max visible-line count (row-height calc)
        self._zero_overlap_skips: int = 0        # consecutive glitch frames skipped

        # --- Coverage detection state ---
        self._covered: bool = False
        self._pre_coverage_lines: list | None = None
        self._pre_coverage_count: int = 0

        self._region_left = REGION_LEFT_PCT
        self._region_top = REGION_TOP_PCT
        self._region_right = REGION_RIGHT_PCT
        self._region_bottom = REGION_BOTTOM_PCT

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

    def set_region(self, left: float, top: float, right: float, bottom: float):
        self._region_left = left
        self._region_top = top
        self._region_right = right
        self._region_bottom = bottom

    def is_running(self):
        return self._running

    def is_paused(self):
        return self._paused

    def get_metrics(self) -> dict:
        """Snapshot of pipeline metrics (for the UI / diagnostics)."""
        return self._metrics.snapshot()

    def _reset_pipeline(self):
        self._stager.reset()
        if self._gate is not None:
            self._gate.reset()
        self._metrics.reset()
        self._last_metrics_log = time.monotonic()
        self._prev_lines = None          # None -> next OCR frame seeds the baseline
        self._reseed_baseline = False
        self._prev_gray = None
        self._visible_estimate = 0
        self._zero_overlap_skips = 0
        self._covered = False
        self._pre_coverage_lines = None
        self._pre_coverage_count = 0

    def start(self):
        if self._running:
            return
        self._paused = False
        self._suppress_events_until = time.monotonic() + SESSION_RESET_DELAY_SECONDS
        self._reset_pipeline()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False
        self._suppress_events_until = time.monotonic() + SESSION_RESET_DELAY_SECONDS
        # Re-establish the baseline on the next frame: loot that arrived (or was
        # already visible) during the pause must not be counted on resume.
        self._reseed_baseline = True

    def stop(self):
        self._paused = False
        self._running = False

    def get_session_reset_delay(self) -> float:
        return SESSION_RESET_DELAY_SECONDS

    # ------------------------------------------------------------------ capture

    def _capture(self):
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            w, h = monitor["width"], monitor["height"]

            region = {
                "left": int(w * self._region_left),
                "top": int(h * self._region_top),
                "width": int(w * (self._region_right - self._region_left)),
                "height": int(h * (self._region_bottom - self._region_top)),
            }

            img = sct.grab(region)

        raw = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
        if OCR_UPSCALE == 1.0:
            return raw
        return raw.resize(
            (round(raw.width * OCR_UPSCALE), round(raw.height * OCR_UPSCALE)),
            Image.LANCZOS,
        )

    def _preprocess_for_ocr(self, pil_img: Image.Image) -> Image.Image:
        """
        Isolate bright text (white, orange, gold, yellow) against the dark
        acquisition-log background. Peak channel keeps coloured text. Vectorised
        with numpy (replaces a per-pixel Python loop — the old hot path).
        """
        BRIGHT_MIN = 135

        arr = np.asarray(pil_img.convert("RGB"))          # H x W x 3, uint8
        peak = arr.max(axis=2)                            # brightest channel per pixel
        mask = peak > BRIGHT_MIN                          # text pixels
        out = np.where(mask, 0, 255).astype(np.uint8)     # black text on white
        return Image.fromarray(out, mode="L").filter(ImageFilter.MinFilter(3))

    def _gray_small(self, pil_img: Image.Image) -> np.ndarray:
        """Downscaled grayscale frame for stability + scroll detection (cheap)."""
        w, h = pil_img.size
        scale = _GRAY_HEIGHT / h if h else 1.0
        small = pil_img.convert("L").resize(
            (max(1, int(w * scale)), _GRAY_HEIGHT), Image.BOX
        )
        return np.asarray(small, dtype=np.float32)

    # ------------------------------------------------------------------- events

    def _handle_committed(self, committed) -> int:
        """Fire committed loot events unless still inside the settle window.

        Events confirmed during the post-start/resume suppression window are the
        items already on screen when tracking began; the stager has already marked
        them committed, so dropping them here prevents counting pre-existing loot.
        """
        if not committed:
            return 0
        if time.monotonic() < self._suppress_events_until:
            return 0
        for ev in committed:
            self._on_event(LootEvent(
                item_name=ev.item,
                quantity=ev.qty,
                zone=self._zone,
                raw_text=ev.item,
                character=CHARACTER_NAME,
            ))
        self._metrics.inc("committed_events", len(committed))
        return len(committed)

    def _emit_missed(self, text: str) -> None:
        """Surface an OCR line that never became a confirmed event (Issue 5).

        Routed to both the rolling Missed_*.log (via main) and the live log, so no
        OCR data is ever silently discarded.
        """
        if self._on_missed is not None:
            self._on_missed(text)

    def _account_new_lines(self, new_lines) -> None:
        """Tally and surface each genuinely-new line: parsed, or MISSED."""
        for nl in new_lines:
            self._metrics.inc("new_lines_detected")
            if nl.qty_parse_failed:
                self._metrics.inc("failed_qty")
            if nl.matched:
                self._metrics.inc("lines_parsed")
            else:
                self._metrics.inc("lines_missed")
                if nl.miss_reason == "unknown_item":
                    self._metrics.inc("unknown_item")
                elif nl.miss_reason == "no_item_text":
                    self._metrics.inc("normalization_failed")
                self._emit_missed(nl.as_missed())

    def _process_frame(self, prev_lines, current_lines, prev_gray, current_gray,
                       allow_skip=True) -> bool:
        """Align prev->current, stage/vote, and fire confirmed events.

        Returns True if the frame was processed, False if it was skipped as a
        transient glitch (caller should keep the previous baseline).
        """
        # Pixel scroll as a validation hint — only when the window looks full
        # (row height is reliable) and the detector is confident.
        expected_new = None
        scroll = None
        if (ENABLE_SCROLL_HINT and prev_gray is not None and current_gray is not None
                and self._visible_estimate > 0 and len(current_lines) >= self._visible_estimate):
            scroll = estimate_scroll_px(prev_gray, current_gray)
            row_h = current_gray.shape[0] / self._visible_estimate
            expected_new = expected_new_lines(scroll, row_h, len(current_lines))

        align_t0 = time.perf_counter()
        result = align(prev_lines, current_lines, self._match_cfg, expected_new)
        self._metrics.record_align((time.perf_counter() - align_t0) * 1000)
        self._metrics.record_confidence(result.confidence)

        # Anti-corruption guards. A frame is "suspicious" when it shares no
        # overlap with the baseline, or claims implausibly many new lines
        # unconfirmed by pixel scroll (the wall-of-identical-lines misalignment).
        # Such frames are skipped and realigned against the same baseline. If the
        # mismatch PERSISTS past the skip budget e.g. the window sits static for
        # a long time while the semi-transparent background bleeds through and
        # jitters the OCR. The baseline is re-established and emits nothing, rather
        # than dumping the whole window into the log as new loot. The coverage
        # realign passes allow_skip=False because that realignment is deliberate.
        zero_susp = is_glitch_frame(result, len(prev_lines), 0)
        jump_susp = is_implausible_jump(result, 0, expected_new, MAX_PLAUSIBLE_NEW)
        if allow_skip and (zero_susp or jump_susp):
            if self._zero_overlap_skips < GLITCH_MAX_SKIPS:
                self._zero_overlap_skips += 1
                self._metrics.inc("frames_glitch_skip")
                if jump_susp:
                    self._metrics.inc("duplicate_suppressed")
                self._emit_diagnostics(result, scroll, expected_new, len(current_lines), 0)
                return False
            # Mismatch persisted -> re-baseline (commit nothing). Prevents a
            # static/jittery window from being re-counted as new loot.
            self._stager.seed(current_lines)
            self._zero_overlap_skips = 0
            self._metrics.inc("reseeds")
            self._emit_diagnostics(result, scroll, expected_new, len(current_lines), 0)
            return True
        self._zero_overlap_skips = 0
        if result.zero_overlap:
            self._metrics.inc("missed_overlap")

        # Account for and surface every new line (parsed -> staged; unresolved -> MISSED).
        self._account_new_lines(result.new_lines)

        # Raw -> cleaned strip log (session logger / [MISS] display), as before.
        if result.new_lines and self._on_strip_result:
            self._on_strip_result([(nl.raw, nl.as_display()) for nl in result.new_lines])

        # Batch zone overrides depend on co-occurrence in the visible window.
        self._current_batch_overrides = resolve_batch_zone_overrides(
            [l.item for l in current_lines if l.item]
        )

        committed = self._stager.observe(result.overlap, current_lines)
        self._handle_committed(committed)

        # Surface resolved loot that scrolled off before it could be confirmed
        # (lost to a large frame gap, e.g. slow OCR). Unresolved drops were already
        # logged as MISSED when first detected, so only resolved ones become LOST.
        for raw, was_resolved in self._stager.drain_dropped():
            if was_resolved:
                self._metrics.inc("lost_unconfirmed")
                self._emit_missed(f"{raw} -> LOST (scrolled off before confirmation)")

        self._emit_diagnostics(result, scroll, expected_new, len(current_lines), len(committed))
        return True

    def _emit_diagnostics(self, result, scroll, expected_new, frame_lines, committed_now):
        if self._on_diagnostics is None:
            return
        diag = FrameDiagnostics(
            frame_lines=frame_lines,
            overlap=result.overlap,
            new_lines=len(result.new_lines),
            confidence=result.confidence,
            zero_overlap=result.zero_overlap,
            scroll_px=scroll.shift_px if scroll else 0,
            scroll_confident=scroll.confident if scroll else False,
            expected_new=expected_new,
            text_new=result.diagnostics.get("lc", frame_lines) - result.diagnostics.get("largest_valid", result.overlap),
            disagreement=result.diagnostics.get("disagreement", False),
            pending=self._stager.pending_count,
            committed_now=committed_now,
            reason=result.diagnostics.get("reason", ""),
        )
        self._on_diagnostics(diag)

    def _maybe_log_metrics(self):
        """Emit a periodic [METRICS] pipeline summary through the metrics callback."""
        if self._on_metrics is None or METRICS_LOG_INTERVAL_SECONDS <= 0:
            return
        now = time.monotonic()
        if now - self._last_metrics_log >= METRICS_LOG_INTERVAL_SECONDS:
            self._last_metrics_log = now
            self._on_metrics(self._metrics.summary())

    # --------------------------------------------------------------------- loop

    def _loop(self):
        while self._running:
            if self._paused:
                time.sleep(0.1)
                continue
            t0 = time.perf_counter()
            try:
                self._tick()
            except Exception:
                from .app_logger import log_caught_exception
                log_caught_exception()
            # Frame processing time covers every path (capture/OCR/align or a skip),
            # so effective_fps reflects the real end-to-end cadence.
            self._metrics.record_frame((time.perf_counter() - t0) * 1000)
            self._maybe_log_metrics()
            time.sleep(POLL_INTERVAL)

    def _tick(self):
        """Process one capture. Returns early (skip) without advancing the baseline
        when the frame is idle, animating, occluded, or a glitch."""
        img = self._capture()
        self._metrics.inc("frames_captured")
        processed_img = self._preprocess_for_ocr(img)
        if self._on_ocr_frame:
            self._on_ocr_frame(img, processed_img)

        gray = self._gray_small(img)

        # Idle skip (performance): frame unchanged -> no new loot, no OCR.
        # Still corroborate pending slots so trailing loot confirms while
        # the player is momentarily not looting.
        if (self._prev_gray is not None and not self._covered
                and self._prev_lines is not None
                and frame_difference(self._prev_gray, gray) < _IDLE_DIFF_EPS):
            self._metrics.inc("frames_idle_skip")
            committed = self._stager.observe(len(self._prev_lines), self._prev_lines)
            self._handle_committed(committed)
            self._prev_gray = gray
            return

        # Optional stability gate: skip OCR mid-animation (opt-in).
        if self._gate is not None and not self._gate.update(gray):
            self._metrics.inc("frames_stability_skip")
            self._prev_gray = gray
            return

        ocr_t0 = time.perf_counter()
        full_text = pytesseract.image_to_string(processed_img, config="--psm 6")
        self._metrics.record_ocr((time.perf_counter() - ocr_t0) * 1000)
        self._metrics.inc("frames_ocr")
        if full_text.strip():
            self._on_ocr(full_text)

        current_lines = normalize_frame(full_text, NAME_FUZZY_THRESHOLD)
        cur_count = len(current_lines)
        self._metrics.inc("ocr_lines_seen", cur_count)
        self._visible_estimate = min(
            self._tracking_window_size, max(self._visible_estimate, cur_count)
        )

        # First frame (or re-seed after resume) -> establish the baseline: mark the
        # currently-visible lines as already-obtained history so they are never
        # counted (Issue 4). Tracking begins only when new lines appear afterward.
        if self._prev_lines is None or self._reseed_baseline:
            self._stager.seed(current_lines)
            self._prev_lines = current_lines
            self._prev_gray = gray
            self._reseed_baseline = False
            return

        # --- Coverage handling: region occluded -> freeze, realign on return.
        if self._covered:
            if cur_count >= self._pre_coverage_count:
                self._covered = False
                baseline = self._pre_coverage_lines or self._prev_lines
                # No scroll hint across an occlusion (frames not comparable);
                # always accept — this realignment is deliberate.
                self._process_frame(baseline, current_lines, None, None, allow_skip=False)
                self._pre_coverage_lines = None
                self._prev_lines = current_lines
            self._prev_gray = gray
            return

        if cur_count < len(self._prev_lines) - _COVERAGE_DROP_THRESHOLD:
            self._covered = True
            self._pre_coverage_lines = self._prev_lines
            self._pre_coverage_count = len(self._prev_lines)
            self._prev_gray = gray
            return

        # --- Normal frame. Advance the baseline only if the frame was
        # accepted; a skipped glitch frame realigns against the same one.
        if self._process_frame(self._prev_lines, current_lines, self._prev_gray, gray):
            self._prev_lines = current_lines
        self._prev_gray = gray
