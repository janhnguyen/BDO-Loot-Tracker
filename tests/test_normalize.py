import unittest
import _bootstrap
from core.normalize import normalize_frame, normalize_line

class NormalizeTests(unittest.TestCase):
    def test_exact_match_with_leading_and_trailing_noise(self):
        nl = normalize_line("s [Underwater Ancient Weapon Power Stone] x7.")
        self.assertEqual(nl.item, "Underwater Ancient Weapon Power Stone")
        self.assertEqual(nl.qty, 7)
        self.assertTrue(nl.matched)
        self.assertEqual(nl.name_confidence, 1.0)

    def test_event_prefix_is_stripped(self):
        nl = normalize_line("*[[Event] Remnant of Distortion].")
        self.assertEqual(nl.item, "Remnant of Distortion")
        self.assertEqual(nl.qty, 1)

    def test_quantity_digit_normalisation(self):
        # 'xl0' -> 10 ('l' normalised to '1').
        nl = normalize_line("[Underwater Ancient Weapon Power Stone] xl0.")
        self.assertEqual(nl.item, "Underwater Ancient Weapon Power Stone")
        self.assertEqual(nl.qty, 10)

    def test_fuzzy_canonicalises_misspelling(self):
        nl = normalize_line("[Ancient Solder Fragment] x2")
        self.assertEqual(nl.item, "Ancient Soldier Fragment")
        self.assertTrue(nl.matched)
        self.assertEqual(nl.qty, 2)
        self.assertLess(nl.name_confidence, 1.0)
        self.assertGreaterEqual(nl.name_confidence, 0.82)

    def test_unknown_item_stays_unresolved(self):
        nl = normalize_line("[Totally Nonexistent Doohickey] x3")
        self.assertIsNone(nl.item)
        self.assertFalse(nl.matched)
        self.assertEqual(nl.as_display(), "")
        self.assertEqual(nl.miss_reason, "unknown_item")

    def test_missed_rendering_preserves_raw(self):
        nl = normalize_line("[Totally Nonexistent Doohickey] x3")
        self.assertEqual(nl.as_missed(), "[Totally Nonexistent Doohickey] x3 -> MISSED")

    def test_missed_rendering_for_qty_one(self):
        nl = normalize_line("[Totally Nonexistent Doohickey]")
        self.assertEqual(nl.as_missed(), "[Totally Nonexistent Doohickey] -> MISSED")

    def test_frame_keeps_only_bracketed_lines_in_order(self):
        text = "garbage line\n[Ancient Spirit Dust]\nmore noise"
        frame = normalize_frame(text)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame[0].item, "Ancient Spirit Dust")
        self.assertEqual(frame[0].qty, 1)

if __name__ == "__main__":
    unittest.main()
