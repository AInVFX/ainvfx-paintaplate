"""Follow Matte when SAM's mask takes a piece of what stands in front (matte workstream, wave 5: the second proposal of wave 4)."""
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


class PieceInFront(unittest.TestCase):
    """For a paint as for an erase (9dc8198), a piece of the tracker's mask that lies mostly on covered places is what
    stands in front, and is left out (13 Nov 2026: pieces of SAM's mask on the horse's head, over the cow's place)."""

    def test_a_piece_of_the_mask_on_what_stands_in_front_is_left_out(self):
        sam, shown, shot, base, front = scene(slice(60, 184))
        sam[20:41, 92:118, 164:172] = 1  # apart from the object's visible part, inside its place's margin, on what stands in front
        out, _ = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, zone=1 / 16, threshold=0.1, element=shown[0].astype(np.float32))
        matte = out > 0.5
        self.assertEqual(int(matte[(slice(20, 41),) + front].sum()), 0)  # at the commit before: 208 px a frame
        self.assertGreaterEqual(float(np.mean([(matte[t] & shown[t]).sum() / shown[t].sum() for t in range(20, 41)])), 0.95)
