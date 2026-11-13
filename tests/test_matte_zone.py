"""Follow Matte while the tracker returns the paint zone it was given (matte workstream, wave 5, M4)."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


def scene(n=24, h=72, w=128):
    """A camera that pans 1 px per frame, an object painted in a paint zone 3.6 times its size and within its reach, and a tracker that
    returns the zone for 10 frames before it finds the object (13 Nov 2026: 10 to 13 frames on each of five cow
    recordings)."""
    rng = np.random.default_rng(7)
    wide = (ndimage.gaussian_filter(rng.random((h, w + n, 3)), (0.7, 0.7, 0)) * 0.6 + 0.2).astype(np.float32)
    base = np.stack([wide[:, t:t + w] for t in range(n)])
    shot = base.copy()
    yy, xx = np.mgrid[:h, :w]
    obj = np.stack([((xx - (70 - t)) / 10.0) ** 2 + ((yy - 36) / 7.0) ** 2 <= 1 for t in range(n)])  # it stands still in the scene
    zone = np.stack([(xx - (70 - t)) ** 2 + (yy - 36) ** 2 <= 16 ** 2 for t in range(n)])
    shot[obj] = (0.95, 0.9, 0.85)
    sam = np.where(np.arange(n)[:, None, None] < 10, zone, obj).astype(np.float32)
    return sam, obj, shot, base


class PaintZone(unittest.TestCase):
    """SAM 3.1, given the paint zone, returns the zone on its first frames: the matte holds the object there."""

    def test_the_matte_holds_the_object_while_the_tracker_returns_the_paint_zone(self):
        sam, obj, shot, base = scene()
        out, summary = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, element=obj[0].astype(np.float32))
        matte = out > 0.5
        areas, tight = matte.reshape(len(matte), -1).sum(1), int(obj[10].sum())
        self.assertLessEqual(int(areas[:13].max()), 1.5 * tight, areas[:14])  # at 32ea0a4: the whole zone, 3.6 times
        for t in range(13):  # no step where the tracker leaves the zone
            self.assertLess(abs(int(areas[t + 1]) - int(areas[t])), 0.3 * max(int(areas[t]), int(areas[t + 1])), (t, areas[:14]))
        for t in range(len(sam)):  # and the object is in the matte on every frame
            self.assertGreaterEqual(int((matte[t] & obj[t]).sum()), 0.95 * int(obj[t].sum()), t)
        self.assertIn("held the paint zone it was given", summary)
        print(f"paint zone: frames 0 to 12 at most {areas[:13].max() / tight:.2f} times the tracker's first tight mask")

    def test_a_first_mask_that_is_the_object_is_not_a_zone(self):
        sam, obj, shot, base = scene()
        first = obj[0].astype(np.float32)
        out, summary = m.follow_matte(obj.astype(np.float32), len(obj), first, shot=shot, base=base, element=first)
        self.assertNotIn("paint zone", summary)
        for t in range(len(obj)):
            self.assertGreaterEqual(int(((out[t] > 0.5) & obj[t]).sum()), 0.95 * int(obj[t].sum()), t)


if __name__ == "__main__":
    unittest.main()
