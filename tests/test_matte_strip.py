"""Follow Matte when a piece leaves the object's place (matte workstream, wave 5: the first proposal of wave 4)."""
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


class LeavingPiece(unittest.TestCase):
    """When less than a quarter of the place holds the object, a found area that reaches beyond the place's margin is left
    out whole: no strip of it stays inside the margin (13 Nov 2026: such a strip stayed on the horse's chest)."""

    def test_a_piece_that_walks_off_with_what_stands_in_front_leaves_no_strip(self):
        sam, shown, shot, base, front = scene(slice(29, 153), walks=True)
        out, summary = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, element=shown[0].astype(np.float32))
        held = [int(((out[t] > 0.5) & shown[t]).sum()) for t in range(70, 106)]
        self.assertEqual(max(held), 0, held)  # at the commit before: a strip inside the margin
        self.assertIn("\n  Removed: pieces that left the object's place, on ", summary)
