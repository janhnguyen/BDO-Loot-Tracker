"""
The acquisition log fades new lines in over a few frames; OCR run mid-animation
produces garbage that pollutes alignment. This gate measures frame-to-frame
change and only reports "stable" once the region has held still for a few
consecutive frames.

It is intentionally conservative: a frame that isn't yet stable only delays OCR
by one tick (~100 ms), it never drops loot.
"""

from __future__ import annotations
import numpy as np

def frame_difference(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """Mean absolute per-pixel difference between two grayscale frames (0..255)."""
    a = np.asarray(prev_gray, dtype=np.float32)
    b = np.asarray(curr_gray, dtype=np.float32)
    if a.shape != b.shape or a.size == 0:
        return float("inf")
    return float(np.mean(np.abs(a - b)))

class StabilityGate:
    """Reports the region as stable after N consecutive low-change frames."""

    def __init__(self, diff_threshold: float = 3.0, min_stable_frames: int = 2):
        self._diff_threshold = diff_threshold
        self._min_stable_frames = max(1, min_stable_frames)
        self._prev: np.ndarray | None = None
        self._stable_run = 0
        self._last_diff = float("inf")

    def reset(self) -> None:
        self._prev = None
        self._stable_run = 0
        self._last_diff = float("inf")

    @property
    def last_diff(self) -> float:
        return self._last_diff

    def update(self, gray: np.ndarray) -> bool:
        """Feed the latest grayscale frame; return True if the region is stable.

        The first frame after a reset is never considered stable (there is no
        baseline to compare against yet).
        """
        gray = np.asarray(gray, dtype=np.float32)
        if self._prev is None:
            self._prev = gray
            self._stable_run = 0
            self._last_diff = float("inf")
            return False

        diff = frame_difference(self._prev, gray)
        self._last_diff = diff
        self._prev = gray
        if diff <= self._diff_threshold:
            self._stable_run += 1
        else:
            self._stable_run = 0
        return self._stable_run >= self._min_stable_frames
