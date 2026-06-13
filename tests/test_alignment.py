import unittest
import _bootstrap
from core.alignment import align, is_glitch_frame, is_implausible_jump
from core.fuzzy import _SimpleLine


def L(item, qty=1, conf=1.0):
    return _SimpleLine(item=item, qty=qty, raw=f"{item} x{qty}", name_confidence=conf)


def items(lines):
    return [(l.item, l.qty) for l in lines]


class AlignmentTests(unittest.TestCase):
    def test_single_item_added(self):
        # Oldest first; one new line at the bottom, oldest falls off the top.
        prev = [L("a"), L("b"), L("c"), L("d")]
        curr = [L("b"), L("c"), L("d"), L("e")]
        r = align(prev, curr)
        self.assertEqual(r.overlap, 3)
        self.assertEqual(items(r.new_lines), [("e", 1)])
        self.assertFalse(r.zero_overlap)

    def test_multiple_items_added(self):
        prev = [L("a"), L("b"), L("c"), L("d"), L("e")]
        curr = [L("d"), L("e"), L("f"), L("g"), L("h")]
        r = align(prev, curr)
        self.assertEqual(r.overlap, 2)
        self.assertEqual(items(r.new_lines), [("f", 1), ("g", 1), ("h", 1)])

    def test_repeated_identical_lines_hardened_lava_chunk(self):
        # The brief's canonical example: only the trailing x4 is genuinely new.
        prev = [L("HLC", 8), L("HLC", 8), L("HLC", 6), L("HLC", 6), L("HLC", 6)]
        curr = [L("HLC", 8), L("HLC", 6), L("HLC", 6), L("HLC", 6), L("HLC", 4)]
        r = align(prev, curr)
        self.assertEqual(r.overlap, 4)
        self.assertEqual(items(r.new_lines), [("HLC", 4)])

    def test_zero_overlap_flagged(self):
        prev = [L("a"), L("b"), L("c")]
        curr = [L("x"), L("y"), L("z")]
        r = align(prev, curr)
        self.assertEqual(r.overlap, 0)
        self.assertTrue(r.zero_overlap)
        self.assertEqual(len(r.new_lines), 3)
        self.assertIn("reason", r.diagnostics)

    def test_tolerates_digit_noise_in_carried_line(self):
        # A carried-over line whose quantity is misread by one OCR-confusable digit
        # must not break the overlap.
        prev = [L("a"), L("b", 8), L("c")]
        curr = [L("b", 6), L("c"), L("d")]
        r = align(prev, curr)
        self.assertEqual(r.overlap, 2)
        self.assertEqual(items(r.new_lines), [("d", 1)])

    def test_scroll_hint_resolves_identical_scroll(self):
        # All lines identical: text alone cannot tell a 1-row scroll from no scroll.
        prev = [L("x", 6)] * 5
        curr = [L("x", 6)] * 5

        # No hint -> assume the largest overlap (nothing new).
        r_none = align(prev, curr)
        self.assertEqual(r_none.overlap, 5)
        self.assertEqual(r_none.new_lines, [])

        # Pixel scroll says one row moved -> exactly one new line.
        r_hint = align(prev, curr, expected_new=1)
        self.assertEqual(r_hint.overlap, 4)
        self.assertEqual(items(r_hint.new_lines), [("x", 6)])
        self.assertTrue(r_hint.diagnostics["disagreement"])

    def test_first_frame_against_empty(self):
        r = align([], [L("a"), L("b")])
        self.assertEqual(r.overlap, 0)
        self.assertFalse(r.zero_overlap)  # empty previous is not a failure
        self.assertEqual(len(r.new_lines), 2)


class GlitchGuardTests(unittest.TestCase):
    def _zero(self):
        return align([L("a"), L("b"), L("c")], [L("x"), L("y"), L("z")])

    def _normal(self):
        return align([L("a"), L("b"), L("c")], [L("b"), L("c"), L("d")])

    def test_flags_sudden_total_overlap_loss(self):
        self.assertTrue(is_glitch_frame(self._zero(), prev_len=3, consecutive_skips=0))

    def test_ignores_when_overlap_exists(self):
        self.assertFalse(is_glitch_frame(self._normal(), prev_len=3, consecutive_skips=0))

    def test_does_not_skip_with_tiny_baseline(self):
        # A genuinely small window shouldn't be treated as a glitch.
        self.assertFalse(is_glitch_frame(self._zero(), prev_len=1, consecutive_skips=0))

    def test_gives_up_after_max_skips(self):
        # After enough consecutive skips, accept the wholesale change.
        self.assertFalse(is_glitch_frame(self._zero(), prev_len=3, consecutive_skips=3))


class ImplausibleJumpTests(unittest.TestCase):
    def _jump(self, new_count):
        # Disjoint frames -> overlap 0 -> new_lines == all of current.
        prev = [L(f"p{i}") for i in range(20)]
        cur = [L(f"c{i}") for i in range(new_count)]
        return align(prev, cur)

    def test_flags_large_unconfirmed_jump(self):
        self.assertTrue(is_implausible_jump(self._jump(15), consecutive_skips=0))

    def test_allows_small_jump(self):
        self.assertFalse(is_implausible_jump(self._jump(3), consecutive_skips=0))

    def test_pixel_scroll_confirmation_overrides(self):
        # If the image actually scrolled that far, accept the jump.
        self.assertFalse(is_implausible_jump(self._jump(15), 0, expected_new=15))

    def test_gives_up_after_max_skips(self):
        self.assertFalse(is_implausible_jump(self._jump(15), consecutive_skips=3))


if __name__ == "__main__":
    unittest.main()
