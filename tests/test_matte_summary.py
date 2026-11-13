"""Follow Matte's summary (matte workstream, wave 5: P3)."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


def scene(front_cols, walks=False, n=121, h=182, w=320):
    """The cow scenes of test_mathops.py: a camera that pans 2 px per frame, a painted object that stands still in the
    scene (or, with `walks`, walks with what stands in front from frame 28), and a front object still in the frame."""
    rng = np.random.default_rng(12 if walks else 11)
    land = ndimage.gaussian_filter(rng.random((h, w + 2 * n, 3)).astype(np.float32), (2, 2, 0))
    land = np.clip(0.5 + 3 * (land - land.mean()), 0, 1)
    base = np.stack([land[:, 2 * t:2 * t + w] for t in range(n)])
    front = (slice(30, 170), front_cols)
    base[(slice(None),) + front] = (0.55, 0.25, 0.10)
    shot, sam, shown = base.copy(), np.zeros((n, h, w), np.float32), np.zeros((n, h, w), bool)
    for t in range(n):
        x = 213 - 2 * (min(t, 28) if walks else t)
        shown[t, 96:116, max(x, 0):max(x + 86, 0)] = True
        if not walks:
            shown[(t,) + front] = False  # behind what stands in front
        shot[t][shown[t]] = (0.9, 0.85, 0.8)
        if t < 11:
            sam[t, 63:149, 207 - 2 * t:305 - 2 * t] = 1  # the paint zone it was given
        elif walks or t < 50:
            sam[t] = shown[t]
    return sam, shown, shot, base, front


class Summary(unittest.TestCase):
    """The ratio to SAM's mask is read only on frames where SAM returned a mask; the others are counted apart."""

    def test_frames_with_no_mask_from_sam_are_counted_apart(self):
        sam, shown, shot, base, front = scene(slice(60, 184))  # SAM loses the object on frame 50; the shot's changes bring it back
        _, summary = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, zone=1 / 16, threshold=0.1, element=shown[0].astype(np.float32))
        found = __import__("re").search(r"added area on \d+ frame\(s\), up to (\d+\.\d) times SAM's mask \((\d+) of them with no mask from SAM\)", summary)
        self.assertIsNotNone(found, summary)  # at the commit before: « up to 1301.0 times SAM's mask », a count of pixels
        self.assertLess(float(found.group(1)), 5.0)
        self.assertGreater(int(found.group(2)), 0)
