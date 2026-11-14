"""Follow Matte measures the object by its own size: a sliver that SAM 3.1 returns is not a sighting, and the guard
against a runaway matte takes the painted object's size, never the paint zone that the tracker returns first."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


def still_scene(n, h=90, w=160):
    """A still camera over a textured plate, and a painted square of 100 px at [40:50, 70:80] on every frame."""
    rng = np.random.default_rng(3)
    base = np.repeat((0.25 + 0.5 * rng.random((1, h, w, 3))).astype(np.float32), n, 0)
    shot = base.copy()
    shot[:, 40:50, 70:80] = (0.2, 0.7, 0.2)
    square = np.zeros((h, w), np.float32)
    square[40:50, 70:80] = 1
    return base, shot, square


class OwnSize(unittest.TestCase):
    def test_a_sliver_is_not_a_sighting(self):
        n = 30
        base, shot, square = still_scene(n)
        masks = np.zeros((n, 90, 160), np.float32)
        masks[:20] = square
        masks[20, 45, 75] = 1  # one pixel of the object, then nothing
        _, summary = m.follow_matte(masks, n, square, shot=shot, base=base, element=square)
        self.assertTrue(summary.startswith("tracked on 20 of 30 frames."), summary)
        self.assertNotIn("Warning", summary)

    def test_the_guard_takes_the_object_not_the_zone(self):
        n = 24
        base, shot, square = still_scene(n)
        shot[:, 43:47, 80:160] = (0.9, 0.9, 0.9)  # a changed strip that starts at the object and runs to the frame's edge
        zone = np.zeros((90, 160), np.float32)
        zone[30:60, 60:90] = 1  # the paint zone: 9 times the object
        masks = np.repeat(square[None], n, 0)
        masks[:3] = zone  # the tracker returns the zone first
        matte, summary = m.follow_matte(masks, n, zone, shot=shot, base=base, element=square)
        self.assertNotIn("Warning: matte", summary)
        self.assertLessEqual(int((matte[-1] > 0.5).sum()), 3 * 100, summary)


if __name__ == "__main__":
    unittest.main()
