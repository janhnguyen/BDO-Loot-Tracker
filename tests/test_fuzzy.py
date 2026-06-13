import unittest
import _bootstrap
from core.fuzzy import (
    MatchConfig,
    _SimpleLine,
    digit_confusable,
    line_similarity,
    names_match,
    quantities_match,
)

def L(item, qty, conf=1.0):
    return _SimpleLine(item=item, qty=qty, raw=f"{item} x{qty}", name_confidence=conf)

class DigitConfusionTests(unittest.TestCase):
    def test_classic_pairs(self):
        self.assertTrue(digit_confusable(8, 6))
        self.assertTrue(digit_confusable(6, 8))
        self.assertTrue(digit_confusable(1, 7))
        self.assertTrue(digit_confusable(17, 11))   # 7<->1 in the ones place
        self.assertTrue(digit_confusable(16, 18))   # 6<->8 in the ones place

    def test_non_confusable(self):
        self.assertFalse(digit_confusable(4, 6))     # not a known pair
        self.assertFalse(digit_confusable(8, 88))    # different lengths
        self.assertFalse(digit_confusable(8, 8))     # identical -> handled elsewhere

    def test_quantities_match(self):
        self.assertEqual(quantities_match(8, 8), (True, 1.0))
        ok, conf = quantities_match(8, 6)
        self.assertTrue(ok)
        self.assertLess(conf, 1.0)
        self.assertFalse(quantities_match(8, 4)[0])  # default tolerance 0, not confusable

    def test_quantity_tolerance_band(self):
        cfg = MatchConfig(qty_tolerance=2, digit_confusion=False)
        self.assertTrue(quantities_match(8, 10, cfg)[0])
        self.assertFalse(quantities_match(8, 11, cfg)[0])

class NameMatchTests(unittest.TestCase):
    def test_exact_and_fuzzy(self):
        self.assertEqual(names_match("Ancient Soldier Fragment", "Ancient Soldier Fragment"),
                         (True, 1.0))
        ok, ratio = names_match("Ancient Soldier Fragment", "Ancient Solder Fragment")
        self.assertTrue(ok)
        self.assertGreater(ratio, 0.9)

    def test_different_names(self):
        ok, ratio = names_match("Apple Pie", "Zebra Crossing")
        self.assertFalse(ok)

class LineSimilarityTests(unittest.TestCase):
    def test_same_line_is_high(self):
        self.assertEqual(line_similarity(L("Lava", 6), L("Lava", 6)), 1.0)

    def test_digit_confused_qty_still_same_line(self):
        # Same item, 8 misread as 6: should stay above the line-accept floor.
        sim = line_similarity(L("Lava", 8), L("Lava", 6))
        self.assertGreaterEqual(sim, MatchConfig().line_accept)

    def test_different_real_qty_is_a_different_drop(self):
        # 6 vs 4 is not a digit confusion -> below the floor (a separate drop).
        sim = line_similarity(L("Lava", 6), L("Lava", 4))
        self.assertLess(sim, MatchConfig().line_accept)

    def test_different_item_is_low(self):
        sim = line_similarity(L("Lava Chunk", 6), L("Spirit Dust", 6))
        self.assertLess(sim, MatchConfig().line_accept)

if __name__ == "__main__":
    unittest.main()
