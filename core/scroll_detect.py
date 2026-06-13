"""
The detector finds the upward pixel shift s that best explains the difference
between two grayscale frames: the new frame's row r should match the old
frame's row r + s.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass
class ScrollResult:
    shift_px: int          # best upward shift in pixels (0 = no scroll)
    score: float           # mean abs pixel diff at shift_px (lower = better fit)
    baseline_score: float  # mean abs pixel diff at shift 0
    confident: bool        # True when the shift meaningfully beats the baseline

def estimate_scroll_px(
    prev_gray: np.ndarray,
    curr_gray: np.ndarray,
    max_shift: int | None = None,
    baseline_eps: float = 2.0,
    improve_ratio: float = 0.5,
) -> ScrollResult:
    """
    Estimate how many pixels curr_gray scrolled up relative to prev_gray.

    baseline_eps: if the frames are nearly identical (mean diff below this),
    report no scroll. improve_ratio: a shift is only confident when its
    residual is below improve_ratio * baseline.
    """
    a = np.asarray(prev_gray, dtype=np.float32)
    b = np.asarray(curr_gray, dtype=np.float32)
    if a.ndim != 2 or a.shape != b.shape or a.shape[0] < 4:
        return ScrollResult(0, 0.0, 0.0, False)

    h = a.shape[0]
    if max_shift is None:
        max_shift = h // 2
    max_shift = max(1, min(max_shift, h - 1))

    baseline = float(np.mean(np.abs(a - b)))
    if baseline < baseline_eps:
        return ScrollResult(0, baseline, baseline, True)

    best_s, best_score = 0, baseline
    for s in range(1, max_shift + 1):
        # New frame scrolled up by s: curr[:h-s] should match prev[s:].
        score = float(np.mean(np.abs(a[s:] - b[: h - s])))
        if score < best_score:
            best_score, best_s = score, s

    confident = best_s > 0 and best_score < baseline * improve_ratio
    return ScrollResult(best_s, best_score, baseline, confident)


def rows_scrolled(shift_px: int, row_height_px: float) -> float:
    """Convert a pixel shift to a (fractional) number of scrolled log rows."""
    if row_height_px <= 0:
        return 0.0
    return shift_px / row_height_px


def expected_new_lines(scroll: ScrollResult, row_height_px: float, max_lines: int) -> int | None:
    """
    Map a scroll result to an expected new-line count, or None if not usable.

    Returns round(shift_px / row_height_px) clamped to [0, max_lines] when
    the detection is confident and the fractional row estimate is close to an
    integer; otherwise None (the caller then relies on text alignment alone).
    """
    if not scroll.confident or row_height_px <= 0:
        return None
    rows = rows_scrolled(scroll.shift_px, row_height_px)
    nearest = round(rows)
    # Reject ambiguous fractional estimates that fall between rows.
    if abs(rows - nearest) > 0.35:
        return None
    return int(max(0, min(max_lines, nearest)))
