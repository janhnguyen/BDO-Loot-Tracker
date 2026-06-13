import unittest
import _bootstrap
from core.tracker import Tracker
from core.normalize import NormalizedLine

def matched(item, qty=1):
    return NormalizedLine(item=item, qty=qty, raw=f"[{item}] x{qty}",
                          name_confidence=1.0, matched=True)

def unmatched(raw, reason="unknown_item"):
    return NormalizedLine(item=None, qty=1, raw=raw, name_confidence=0.0,
                          matched=False, miss_reason=reason)

class TrackerObservabilityTests(unittest.TestCase):
    def _tracker(self):
        self.events = []
        self.missed = []
        t = Tracker(
            on_event=lambda e: self.events.append(e),
            on_ocr=lambda x: None,
            on_missed=lambda s: self.missed.append(s),
        )
        return t

    def test_unmatched_new_line_emits_missed_and_metrics(self):
        t = self._tracker()
        prev = [matched("Known A")]
        cur = [matched("Known A"), unmatched("THAN Crystal of Ruin x1")]
        t._process_frame(prev, cur, None, None, allow_skip=False)

        self.assertEqual(self.missed, ["THAN Crystal of Ruin x1 -> MISSED"])
        m = t.get_metrics()
        self.assertEqual(m["new_lines_detected"], 1)
        self.assertEqual(m["lines_missed"], 1)
        self.assertEqual(m["unknown_item"], 1)
        self.assertEqual(m["lines_parsed"], 0)

    def test_matched_new_line_is_not_missed(self):
        t = self._tracker()
        prev = [matched("Known A")]
        cur = [matched("Known A"), matched("Known B")]
        t._process_frame(prev, cur, None, None, allow_skip=False)

        self.assertEqual(self.missed, [])
        m = t.get_metrics()
        self.assertEqual(m["lines_parsed"], 1)
        self.assertEqual(m["lines_missed"], 0)

    def test_normalization_failure_is_categorised(self):
        t = self._tracker()
        prev = [matched("Known A")]
        cur = [matched("Known A"), unmatched("[]", reason="no_item_text")]
        t._process_frame(prev, cur, None, None, allow_skip=False)

        m = t.get_metrics()
        self.assertEqual(m["normalization_failed"], 1)
        self.assertEqual(len(self.missed), 1)

if __name__ == "__main__":
    unittest.main()
