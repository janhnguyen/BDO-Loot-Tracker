import random
import unittest
from collections import Counter
import _bootstrap
from core.alignment import align
from core.fuzzy import MatchConfig, _SimpleLine
from core.staging import LootStager

def L(item, qty):
    return _SimpleLine(item=item, qty=qty, raw=f"{item} x{qty}", name_confidence=1.0)

GROUP = [
    ("Black Stone", 8),
    ("Herald's Crystal", 1),
    ("Ancient Spirit Dust", 10),
    ("Caphras Stone", 5),
    ("Hardened Lava Chunk", 1047),  # OCR mega-misread, a unique anchor by quantity
]

def _build_truth(n=300, seed=3):
    rng = random.Random(seed)
    truth = []
    for i in range(n):
        if i % 30 == 5:
            truth.extend(GROUP)
        else:
            truth.append(("Hardened Lava Chunk", rng.choice([9, 12])))
    return truth

def _drive(truth, window=18, min_sightings=3, expected_new_each=None):
    cfg = MatchConfig()
    stager = LootStager(min_sightings=min_sightings)
    prev = []
    committed = Counter()
    for n in range(1, len(truth) + 1):
        vis = [L(it, q) for it, q in truth[max(0, n - window):n]]
        r = align(prev, vis, cfg, expected_new=expected_new_each)
        for ev in stager.observe(r.overlap, vis):
            committed[(ev.item, ev.qty)] += 1
        prev = vis
    for ev in stager.flush():
        committed[(ev.item, ev.qty)] += 1
    return committed

class ZephyrosDuplicateTests(unittest.TestCase):
    def test_no_item_is_ever_overcounted(self):
        truth = _build_truth()
        truth_count = Counter(truth)
        committed = _drive(truth)
        for key, n in truth_count.items():
            self.assertLessEqual(
                committed[key], n,
                msg=f"{key} over-counted: tracked {committed[key]} vs actual {n}",
            )

    def test_distinctive_high_value_drops_counted_exactly_once_each(self):
        # The unique anchors (different item or quantity from the HLC wall) must be counted exactly as often as they dropped.
        truth = _build_truth()
        truth_count = Counter(truth)
        committed = _drive(truth)
        for key in (("Herald's Crystal", 1), ("Caphras Stone", 5),
                    ("Hardened Lava Chunk", 1047), ("Black Stone", 8)):
            self.assertEqual(committed[key], truth_count[key], msg=str(key))

    def test_pixel_scroll_hint_recovers_identical_wall(self):
        # With the scroll hint (1 new row/frame) even the pure-identical HLC runs are counted exactly.
        truth = _build_truth()
        committed = _drive(truth, expected_new_each=1)
        # Every drop accounted for exactly once.
        self.assertEqual(sum(committed.values()), len(truth))


if __name__ == "__main__":
    unittest.main()
