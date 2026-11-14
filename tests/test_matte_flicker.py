"""A figure for a matte that flickers (matte workstream, wave 7, backlog D9)."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402



class Flicker(unittest.TestCase):
    """The share of a matte that appears or disappears for 3 frames at most, then comes back as it was."""
    N, H, W = 40, 180, 320

    def body(self, dx=0):
        mm = np.zeros((self.H, self.W), bool)
        mm[60:120, 100 + dx:140 + dx] = True  # 40 x 60 px
        return mm

    def arm(self, mm, dx=0):
        mm[70:80, 140 + dx:164 + dx] = True  # 24 x 10 px, joined to the body
        return mm

    def test_a_still_matte_and_a_moving_one_do_not_flicker(self):
        self.assertEqual(float(m.matte_flicker(np.stack([self.arm(self.body()) for t in range(self.N)])).max()), 0.0)
        self.assertEqual(float(m.matte_flicker(np.stack([self.arm(self.body(t), t) for t in range(self.N)])).max()), 0.0)  # 1 px a frame

    def test_an_arm_lost_on_one_frame_then_on_three(self):
        frames = [self.arm(self.body()) for t in range(self.N)]
        for t in (10, 20, 21, 22):
            frames[t] = self.body()
        f = m.matte_flicker(np.stack(frames))
        self.assertEqual(np.flatnonzero(f > 0).tolist(), [10, 20, 21, 22])
        self.assertAlmostEqual(float(f[10]), 240 / 2640, places=4)  # the arm, whole, against the whole matte

    def test_what_comes_or_goes_for_good_does_not_count(self):
        frames = [self.arm(self.body()) if t < 25 else np.zeros((self.H, self.W), bool) for t in range(self.N)]  # hidden from 25
        frames[5] = np.zeros((self.H, self.W), bool)  # lost on frame 5 only: that counts
        f = m.matte_flicker(np.stack(frames))
        self.assertEqual(np.flatnonzero(f > 0).tolist(), [5])
        self.assertAlmostEqual(float(f[5]), 1.0)

    def test_a_piece_far_from_the_object_for_two_frames(self):
        frames = [self.body() for t in range(self.N)]
        for t in (30, 31):
            frames[t][10:30, 10:40] = True  # 600 px
        f = m.matte_flicker(np.stack(frames))
        self.assertEqual(np.flatnonzero(f > 0).tolist(), [30, 31])
        self.assertAlmostEqual(float(f[30]), 600 / 3000, places=4)
