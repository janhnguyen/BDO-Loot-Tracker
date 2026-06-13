import unittest
import _bootstrap
from core.parser import _clean_line, _fix_leading_ocr
from core.normalize import normalize_line

class LeadingOcrFixTests(unittest.TestCase):
    def test_leading_than_becomes_han(self):
        self.assertEqual(_fix_leading_ocr("THAN Crystal of Ruin"), "HAN Crystal of Ruin")

    def test_clean_line_fixes_han_items(self):
        self.assertEqual(_clean_line("[THAN Crystal of Ruin] x1"), "HAN Crystal of Ruin x1")
        self.assertEqual(_clean_line("THAN Crystal of Dusky Ruin"), "HAN Crystal of Dusky Ruin")

    def test_does_not_corrupt_midword_than(self):
        # The old blanket replace would have mangled these real item names.
        for name in ("Ancient Markthanan's Gland", "Levathan Shard", "Vourethan Shard"):
            self.assertEqual(_fix_leading_ocr(name), name)

    def test_han_items_resolve_to_canonical(self):
        for raw, expected in (
            ("[HAN Crystal of Ruin].", "HAN Crystal of Ruin"),
            ("THAN Crystal of Ruin x1", "HAN Crystal of Ruin"),
            ("[THAN Crystal of Dusky Ruin] x1", "HAN Crystal of Dusky Ruin"),
        ):
            self.assertEqual(normalize_line(raw).item, expected)

    def test_false_positive_items_still_resolve_unchanged(self):
        for raw, expected in (
            ("[Ancient Markthanan's Gland] x2", "Ancient Markthanan's Gland"),
            ("[Levathan Shard] x3", "Levathan Shard"),
            ("[Vourethan Shard] x1", "Vourethan Shard"),
        ):
            self.assertEqual(normalize_line(raw).item, expected)

if __name__ == "__main__":
    unittest.main()
