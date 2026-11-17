"""Follow Matte's « Held » line counts only frames where the held matte is still in the matte as it ends."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


class HeldAfterEmptied(unittest.TestCase):
    def test_frames_emptied_after_they_held_are_not_held(self):
        """A painted square keeps its place to frame 12, leaves it on frame 13, then a small piece of it shows inside
        the place on frame 14, and SAM sees nothing after. The object never comes back, so the matte holds nothing
        from frame 13: the frames where the piece's matte held are emptied, and none of them counts as held."""
        n, h, w = 30, 96, 128
        rng = np.random.default_rng(18)
        base = np.repeat(ndimage.gaussian_filter(rng.random((h, w, 3)).astype(np.float32), (2, 2, 0))[None], n, 0)
        shot, masks = base.copy(), np.zeros((n, h, w), np.float32)
        place, bar, piece = (slice(40, 56), slice(40, 56)), (slice(40, 56), slice(60, 63)), (slice(45, 51), slice(45, 51))
        for t, at in [(t, place) for t in range(12)] + [(12, bar), (13, piece)]:  # the bar lies beyond the place's margin of half a zone, within a zone
            masks[(t,) + at], shot[(t,) + at] = 1.0, (0.9, 0.1, 0.1)
        out, summary = m.follow_matte(masks, n, masks[0], shot=shot, base=base, zone=1 / 16, threshold=0.1)
        self.assertEqual(int(out[12:].sum()), 0, summary)  # the object never came back: from frame 13 the matte holds nothing
        self.assertNotIn("Held:", summary)


if __name__ == "__main__":
    unittest.main()
