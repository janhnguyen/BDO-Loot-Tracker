"""
Thread-safe metrics for the OCR -> parse -> align -> track pipeline.

The tracker mutates these from its worker thread; the UI reads a snapshot. A
single lock guards everything so reads are consistent. Latency is tracked as a
running sum/max/count so we can report average and worst-case without storing
every sample.

Counters (see TrackerMetrics.summary) exist so that no OCR data is ever 
lost: every stage that can drop a line increments a counter, and the
totals are logged periodically and on stop.
"""
from __future__ import annotations
import threading

# All integer counters. Kept explicit so a typo'd name raises instead of silently
# creating a new bucket.
_COUNTERS = (
    "frames_captured",       # frames grabbed from the screen
    "frames_ocr",            # frames actually sent through OCR
    "frames_idle_skip",      # frames skipped because the region was unchanged
    "frames_stability_skip", # frames skipped by the stability gate (animation)
    "frames_glitch_skip",    # frames skipped as alignment glitches (zero/implausible overlap)
    "ocr_lines_seen",        # gross bracketed OCR lines read (sum over frames)
    "new_lines_detected",    # genuinely-new lines from alignment
    "lines_parsed",          # new lines resolved to a known item
    "lines_missed",          # new lines that failed to resolve -> MISSED
    "unknown_item",          # ... of those, name read but not in the item DB
    "normalization_failed",  # ... of those, no item text could be isolated
    "failed_qty",            # lines where the quantity token was unparseable
    "committed_events",      # confirmed loot events emitted
    "lost_unconfirmed",      # resolved slots that scrolled off before confirmation -> LOST
    "duplicate_suppressed",  # frames rejected by the implausible-jump guard
    "missed_overlap",        # populated frames that shared no overlap with the prior frame
    "reseeds",               # baseline re-established after a persistent mismatch (emit nothing)
)

class _Latency:
    __slots__ = ("sum", "max", "n")

    def __init__(self) -> None:
        self.sum = 0.0
        self.max = 0.0
        self.n = 0

    def record(self, ms: float) -> None:
        self.sum += ms
        self.n += 1
        if ms > self.max:
            self.max = ms

    @property
    def avg(self) -> float:
        return self.sum / self.n if self.n else 0.0

class TrackerMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._c = {k: 0 for k in _COUNTERS}
            self._ocr = _Latency()
            self._frame = _Latency()
            self._align = _Latency()
            self._conf_sum = 0.0
            self._conf_n = 0

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._c[name] += n

    def record_ocr(self, ms: float) -> None:
        with self._lock:
            self._ocr.record(ms)

    def record_frame(self, ms: float) -> None:
        with self._lock:
            self._frame.record(ms)

    def record_align(self, ms: float) -> None:
        with self._lock:
            self._align.record(ms)

    def record_confidence(self, conf: float) -> None:
        with self._lock:
            self._conf_sum += conf
            self._conf_n += 1

    def snapshot(self) -> dict:
        with self._lock:
            d = dict(self._c)
            d["ocr_ms_avg"] = round(self._ocr.avg, 1)
            d["ocr_ms_max"] = round(self._ocr.max, 1)
            d["frame_ms_avg"] = round(self._frame.avg, 1)
            d["frame_ms_max"] = round(self._frame.max, 1)
            d["align_ms_avg"] = round(self._align.avg, 2)
            d["align_conf_avg"] = round(self._conf_sum / self._conf_n, 3) if self._conf_n else 0.0
            d["effective_fps"] = round(1000.0 / self._frame.avg, 1) if self._frame.avg else 0.0
            return d

    def summary(self) -> str:
        d = self.snapshot()
        return (
            "[METRICS] "
            f"frames ocr={d['frames_ocr']} idle={d['frames_idle_skip']} "
            f"stab={d['frames_stability_skip']} glitch={d['frames_glitch_skip']} | "
            f"lines new={d['new_lines_detected']} parsed={d['lines_parsed']} "
            f"missed={d['lines_missed']} (unknown={d['unknown_item']} "
            f"normfail={d['normalization_failed']} badqty={d['failed_qty']}) | "
            f"events ok={d['committed_events']} lost={d['lost_unconfirmed']} "
            f"dup_suppressed={d['duplicate_suppressed']} no_overlap={d['missed_overlap']} "
            f"reseeds={d['reseeds']} | "
            f"conf={d['align_conf_avg']:.2f} "
            f"ocr={d['ocr_ms_avg']:.0f}/{d['ocr_ms_max']:.0f}ms "
            f"frame={d['frame_ms_avg']:.0f}/{d['frame_ms_max']:.0f}ms "
            f"({d['effective_fps']:.1f}fps)"
        )
