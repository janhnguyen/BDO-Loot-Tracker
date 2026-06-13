import unittest
import _bootstrap
from core.alignment import align
from core.fuzzy import _SimpleLine
from core.staging import LootStager

def L(item, qty=1, conf=1.0):
    return _SimpleLine(item=item, qty=qty, raw=f"{item} x{qty}", name_confidence=conf)

def drive(stager, frames):
    """Feed frames through align->observe exactly like the tracker loop does."""
    prev = []
    committed = []
    for cur in frames:
        r = align(prev, cur)
        committed.extend(stager.observe(r.overlap, cur))
        prev = cur
    return committed

class StagingTests(unittest.TestCase):
    def test_commits_after_two_sightings(self):
        stager = LootStager(min_sightings=2)
        committed = drive(stager, [[L("a", 3)], [L("a", 3)], [L("a", 3)]])
        self.assertEqual([(e.item, e.qty) for e in committed], [("a", 3)])

    def test_no_double_count_when_line_persists(self):
        stager = LootStager(min_sightings=2)
        committed = drive(stager, [[L("a")]] * 8)
        self.assertEqual(len(committed), 1)  # committed exactly once

    def test_transient_ghost_is_rejected(self):
        # Seen once, gone next frame -> never commits.
        stager = LootStager(min_sightings=2)
        committed = drive(stager, [[L("ghost")], []])
        self.assertEqual(committed, [])
        self.assertGreaterEqual(stager.dropped_unconfirmed, 1)

    def test_majority_vote_on_quantity(self):
        # Quantity read as 6, then 8, then 8 -> commit 8.
        stager = LootStager(min_sightings=3)
        committed = drive(stager, [[L("a", 6)], [L("a", 8)], [L("a", 8)]])
        self.assertEqual(len(committed), 1)
        self.assertEqual(committed[0].item, "a")
        self.assertEqual(committed[0].qty, 8)
        self.assertEqual(committed[0].sightings, 3)

    def test_unknown_item_never_commits(self):
        stager = LootStager(min_sightings=2)
        unknown = _SimpleLine(item=None, qty=1, raw="???", name_confidence=0.0)
        committed = drive(stager, [[unknown], [unknown], [unknown]])
        self.assertEqual(committed, [])

    def test_full_scroll_off_drops_unconfirmed(self):
        # Extreme: entire window replaced between two frames (documented edge).
        stager = LootStager(min_sightings=2)
        committed = drive(stager, [[L("a"), L("b"), L("c")], [L("d"), L("e"), L("f")]])
        self.assertEqual(committed, [])
        self.assertEqual(stager.dropped_unconfirmed, 3)

    def test_realistic_scroll_commits_each_drop_once(self):
        # A steady stream: each frame adds one new line at the bottom.
        stager = LootStager(min_sightings=2)
        frames = [
            [L("a"), L("b"), L("c")],
            [L("b"), L("c"), L("d")],
            [L("c"), L("d"), L("e")],
            [L("d"), L("e"), L("f")],
            [L("e"), L("f"), L("g")],
        ]
        committed = drive(stager, frames)
        names = [e.item for e in committed]
        # b..f each get a 2nd sighting and confirm exactly once; a is dropped
        # (never re-seen) and g is still pending at the end.
        self.assertEqual(names, ["b", "c", "d", "e", "f"])

class SeedAndDrainTests(unittest.TestCase):
    def test_seeded_baseline_is_never_counted(self):
        # Items already on screen at startup must not be counted.
        # Mirrors the tracker: seed sets the baseline, then subsequent frames
        # align against it (prev starts as the baseline, not empty).
        stager = LootStager(min_sightings=2)
        baseline = [L("a"), L("b"), L("c")]
        stager.seed(baseline)
        prev = baseline
        committed = []
        for cur in ([L("b"), L("c"), L("d")], [L("c"), L("d"), L("e")]):
            r = align(prev, cur)
            committed.extend(stager.observe(r.overlap, cur))
            prev = cur
        names = [e.item for e in committed]
        self.assertNotIn("a", names)
        self.assertNotIn("b", names)
        self.assertNotIn("c", names)
        self.assertIn("d", names)

    def test_drain_dropped_separates_lost_from_ghost(self):
        # A resolved line that scrolls off unconfirmed is LOST; an unresolved
        # ghost is just a miss. Both must be reported, distinctly.
        stager = LootStager(min_sightings=3)
        real = L("real", 2)
        ghost = _SimpleLine(item=None, qty=1, raw="??garbage", name_confidence=0.0)
        drive(stager, [[real, ghost], [], []])
        records = stager.drain_dropped()
        resolved = [raw for raw, ok in records if ok]
        unresolved = [raw for raw, ok in records if not ok]
        self.assertIn("real x2", resolved)
        self.assertIn("??garbage", unresolved)
        self.assertEqual(stager.lost_unconfirmed, 1)
        # drain clears the buffer
        self.assertEqual(stager.drain_dropped(), [])

if __name__ == "__main__":
    unittest.main()
