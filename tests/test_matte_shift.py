"""A road that the shot only shifted by a few pixels is no change: the paint matte does not grow onto it."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


class ShiftedRoad(unittest.TestCase):
    def test_the_paint_matte_keeps_off_a_road_that_only_shifted(self):
        """A red square is painted on a textured road; around it, within a zone, the shot shows the road shifted by
        2 px, as a regenerated frame can. Every value there lies within the plate's own range 2 px around it."""
        n, h, w = 10, 352, 640
        rng = np.random.default_rng(20)
        road = ndimage.gaussian_filter(rng.random((h, w, 3)).astype(np.float32), (2, 2, 0))
        road = np.clip(0.5 + 4 * (road - road.mean()), 0, 1)
        square, around = (slice(150, 200), slice(290, 350)), (slice(120, 230), slice(260, 380))
        base, shot = np.repeat(road[None], n, 0), np.repeat(road[None], n, 0)
        shot[(slice(None),) + around] = np.roll(road, 2, axis=1)[around]  # the road beside the paint, 2 px to the right
        shot[(slice(None),) + square] = (0.9, 0.1, 0.1)
        masks = np.zeros((n, h, w), np.float32)
        masks[(slice(None),) + square] = 1.0
        out, summary = m.follow_matte(masks, n, masks[0], shot=shot, base=base, zone=1 / 16, threshold=0.1)
        largest = int((out > 0.5).reshape(n, -1).sum(1).max())
        self.assertLessEqual(largest, 1.2 * 50 * 60, summary)


if __name__ == "__main__":
    unittest.main()
