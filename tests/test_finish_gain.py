"""mathops.hdr_match fits each frame's gain and smooths the gains over 9 frames (smooth_gains): a drift in SDR to HDR's
level goes, and no flicker comes."""
import sys
import unittest

from _env import ROOT, require

require("numpy", "scipy")
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import mathops as m  # noqa: E402


class SmoothGains(unittest.TestCase):
    def test_a_straight_drift_comes_out_as_it_went_in_to_the_first_and_last_frames(self):
        gains = [np.array([0.02 * i, -0.01 * i, 0.3]) for i in range(20)]
        for g, s in zip(gains, m.smooth_gains(gains)):
            np.testing.assert_allclose(s, g, atol=1e-9)

    def test_a_frame_off_by_noise_moves_by_a_fraction_and_a_frame_with_no_gain_takes_its_neighbours_line(self):
        gains = [np.full(3, 0.1) for _ in range(15)]
        gains[7], gains[3] = np.full(3, 0.19), None
        out = m.smooth_gains(gains)
        self.assertLess(abs(out[7][0] - 0.1), 0.02)  # 0.09 stops off on one frame: a ninth of it, near enough
        np.testing.assert_allclose(out[3], 0.1, atol=0.02)
        self.assertEqual(m.smooth_gains([None, None]), [None, None])


class FrameByFrame(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.n, h, w = 30, 32, 48
        self.plate = np.exp2(rng.uniform(-5, 1.5, (self.n, h, w, 3))).astype(np.float32)
        self.none = np.zeros((self.n, h, w), np.float32)

    def match(self, shot, changed):
        return m.hdr_match(self.n, lambda i: shot[i], lambda i: self.plate[i], lambda i: changed[i], grow=1, step=1, workers=2)

    def level(self, out):
        return [float(np.median(np.log2(o / p))) for o, p in zip(out, self.plate)]

    def test_a_drift_of_the_level_over_the_shot_goes(self):
        drift = 0.19 - 0.24 * (1 - np.exp(-np.arange(self.n) / 10.0))  # brighter first frames, as SDR to HDR made them
        shot = (self.plate * np.exp2(drift)[:, None, None, None]).astype(np.float32)
        out, report = self.match(shot, self.none)
        self.assertTrue(report["fitted"])
        self.assertLess(max(abs(v) for v in self.level(out)), 0.01)
        self.assertEqual(len(report["frames"]), self.n)
        self.assertIn("frame by frame", report["text"])

    def test_one_level_for_the_whole_shot_stays_one_gain(self):
        shot = (self.plate * np.array([0.6, 0.55, 0.7], np.float32)).astype(np.float32)
        out, report = self.match(shot, self.none)
        np.testing.assert_allclose(report["frames"], [list(-np.log2([0.6, 0.55, 0.7]))] * self.n, atol=1e-4)
        np.testing.assert_allclose(out[5], self.plate[5], rtol=1e-3)

    def test_frames_whose_edit_covers_everything_take_the_line_of_the_frames_around_them(self):
        drift = np.linspace(0.2, -0.1, self.n)
        shot = (self.plate * np.exp2(drift)[:, None, None, None]).astype(np.float32)
        changed = self.none.copy()
        changed[12:15] = 1  # nothing untouched on frames 12 to 14
        out, report = self.match(shot, changed)
        for i in (12, 13, 14):
            self.assertLess(abs(float(np.mean(report["frames"][i])) + drift[i]), 0.01, i)


if __name__ == "__main__":
    unittest.main()
