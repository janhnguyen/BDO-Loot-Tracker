import unittest
import numpy as np
import _bootstrap
from core.scroll_detect import ScrollResult, estimate_scroll_px, expected_new_lines, rows_scrolled

def _gradient(h=40, w=20):
    """A frame whose rows are distinct, so a vertical shift is detectable."""
    return ((np.arange(h)[:, None] * 13 + np.arange(w)[None, :] * 5) % 256).astype(np.float32)

class ScrollDetectTests(unittest.TestCase):
    def test_detects_upward_shift(self):
        h, w, s = 40, 20, 3
        base = _gradient(h, w)
        curr = np.empty_like(base)
        curr[: h - s] = base[s:]
        curr[h - s:] = ((np.arange(s)[:, None] * 29 + 100) % 256)  # newly exposed rows
        res = estimate_scroll_px(base, curr)
        self.assertEqual(res.shift_px, s)
        self.assertTrue(res.confident)

    def test_no_scroll_on_identical_frames(self):
        f = _gradient()
        res = estimate_scroll_px(f, f.copy())
        self.assertEqual(res.shift_px, 0)
        self.assertTrue(res.confident)

    def test_rejects_degenerate_input(self):
        res = estimate_scroll_px(np.zeros((2, 2), np.float32), np.zeros((2, 2), np.float32))
        self.assertEqual(res.shift_px, 0)
        self.assertFalse(res.confident)

    def test_rows_scrolled(self):
        self.assertEqual(rows_scrolled(10, 5), 2.0)
        self.assertEqual(rows_scrolled(10, 0), 0.0)

    def test_expected_new_lines_when_confident(self):
        res = ScrollResult(shift_px=10, score=1.0, baseline_score=50.0, confident=True)
        self.assertEqual(expected_new_lines(res, row_height_px=5, max_lines=20), 2)

    def test_expected_new_lines_none_when_unconfident(self):
        res = ScrollResult(shift_px=10, score=40.0, baseline_score=50.0, confident=False)
        self.assertIsNone(expected_new_lines(res, 5, 20))

    def test_expected_new_lines_rejects_fractional(self):
        # 13px / 5px = 2.6 rows -> ambiguous, between rows -> None.
        res = ScrollResult(shift_px=13, score=1.0, baseline_score=50.0, confident=True)
        self.assertIsNone(expected_new_lines(res, 5, 20))


if __name__ == "__main__":
    unittest.main()
