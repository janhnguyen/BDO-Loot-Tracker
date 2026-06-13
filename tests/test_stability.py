import unittest
import numpy as np
import _bootstrap
from core.stability import StabilityGate, frame_difference

def _frame(value, h=20, w=20):
    return np.full((h, w), value, dtype=np.float32)

class FrameDifferenceTests(unittest.TestCase):
    def test_identical_frames_zero_diff(self):
        self.assertEqual(frame_difference(_frame(50), _frame(50)), 0.0)

    def test_diff_is_mean_abs(self):
        self.assertEqual(frame_difference(_frame(10), _frame(40)), 30.0)

    def test_shape_mismatch_is_infinite(self):
        self.assertEqual(frame_difference(np.zeros((2, 2)), np.zeros((3, 3))), float("inf"))

class StabilityGateTests(unittest.TestCase):
    def test_first_frame_never_stable(self):
        gate = StabilityGate(diff_threshold=3.0, min_stable_frames=2)
        self.assertFalse(gate.update(_frame(100)))

    def test_becomes_stable_after_quiet_frames(self):
        gate = StabilityGate(diff_threshold=3.0, min_stable_frames=2)
        gate.update(_frame(100))            # baseline
        self.assertFalse(gate.update(_frame(100)))  # 1 quiet frame
        self.assertTrue(gate.update(_frame(100)))   # 2 quiet frames -> stable

    def test_motion_resets_the_run(self):
        gate = StabilityGate(diff_threshold=3.0, min_stable_frames=2)
        gate.update(_frame(100))
        gate.update(_frame(100))            # 1 quiet
        self.assertFalse(gate.update(_frame(200)))  # big change resets
        self.assertFalse(gate.update(_frame(200)))  # 1 quiet again
        self.assertTrue(gate.update(_frame(200)))   # 2 quiet -> stable

    def test_reset_clears_state(self):
        gate = StabilityGate(diff_threshold=3.0, min_stable_frames=2)
        gate.update(_frame(100))
        gate.update(_frame(100))
        gate.reset()
        self.assertFalse(gate.update(_frame(100)))  # baseline again after reset

if __name__ == "__main__":
    unittest.main()
