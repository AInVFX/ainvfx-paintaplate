"""PL10: phase_shift on a soft texture, as plate_move reads it (from the matte agent): a pan of 1 px per frame at 128 px
of width, in plate_move's 25 px tiles. It reads short, and this pins the limit: 0.33 px at a blur of 2 px, 0.90 at 1.5 px,
0.99 at 0.7 px (the matte agent read 0.27, 0.86 and 0.99 on its own texture). The window's mean taken out and the cross
spectrum whitened halfway read 0.85, 0.92 and 0.99, but change three of Follow Matte's tests: the matte agent's call."""
import sys
import unittest

from _env import ROOT, require

require("numpy", "scipy")
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
import mathops  # noqa: E402


def pan(sigma, seed, w=128, h=72):
    """Two luma frames of a random texture blurred at `sigma`, the second panned by 1 px."""
    tex = ndimage.gaussian_filter(np.random.default_rng(seed).random((h, w + 40)).astype(np.float32), sigma)
    return tex[:, 20:20 + w], tex[:, 21:21 + w]


class SoftTexture(unittest.TestCase):
    def test_a_pan_of_one_pixel_reads_short_on_a_soft_texture(self):
        for sigma, lo, hi in ((2.0, 0.25, 0.45), (1.5, 0.85, 0.95), (0.7, 0.97, 1.02)):
            for seed in (0, 1, 2):
                dy, dx = mathops.plate_move(*pan(sigma, seed))
                self.assertTrue(lo < abs(dx) < hi and abs(dy) < 0.05, (sigma, seed, dy, dx))

    def test_a_whole_pixel_shift_on_a_sharp_texture_is_exact(self):
        tex = np.random.default_rng(3).random((64, 96)).astype(np.float32)
        dy, dx = mathops.phase_shift(tex[:, 10:74], tex[:, 13:77], 8.0)
        self.assertAlmostEqual(abs(dx), 3.0, delta=0.02)
        self.assertAlmostEqual(dy, 0.0, delta=0.02)


if __name__ == "__main__":
    unittest.main()
