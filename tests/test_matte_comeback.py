"""Follow Matte when the object comes out from behind what the plate holds in front (matte workstream, wave 5, M5)."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


def scene(n=121, h=182, w=320):
    """FollowMatteBehindThePlate's scene in test_mathops.py, with what stands in front touching the object on frame 0: a
    camera that pans 2 px per frame, a painted object that stands still in the scene, a front object that stands still
    in the frame."""
    rng = np.random.default_rng(11)
    land = ndimage.gaussian_filter(rng.random((h, w + 2 * n, 3)).astype(np.float32), (2, 2, 0))
    land = np.clip(0.5 + 3 * (land - land.mean()), 0, 1)
    base = np.stack([land[:, 2 * t:2 * t + w] for t in range(n)])
    front = (slice(30, 170), slice(89, 213))  # its right edge is the object's left edge on frame 0
    base[(slice(None),) + front] = (0.55, 0.25, 0.10)
    shot, sam, shown = base.copy(), np.zeros((n, h, w), np.float32), np.zeros((n, h, w), bool)
    for t in range(n):
        x = 213 - 2 * t
        shown[t, 96:116, max(x, 0):max(x + 86, 0)] = True
        shown[(t,) + front] = False
        shot[t][shown[t]] = (0.9, 0.85, 0.8)
        if t < 11:
            sam[t, 63:149, 207 - 2 * t:305 - 2 * t] = 1  # the paint zone it was given
        elif t < 50:
            sam[t] = shown[t]  # then the object, until it is lost behind what stands in front
    shot[40:, 90:122, 179:213] = (0.3, 0.2, 0.15)  # LTX changes what stands in front
    return sam, shown, shot, base, front


class Comeback(unittest.TestCase):
    """What touched the object on frame 0 is no part of its place's first look."""

    def test_the_object_comes_back_soon_after_what_touched_it_on_frame_0_has_passed(self):
        sam, shown, shot, base, front = scene()
        out, _ = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, zone=1 / 16, threshold=0.1, element=shown[0].astype(np.float32))
        matte = out > 0.5
        hidden = [t for t in range(20, len(sam)) if not shown[t].any()]
        self.assertEqual((hidden[0], hidden[-1]), (43, 62))  # it comes out on frame 63
        self.assertEqual(int(matte[hidden].sum()), 0)  # empty while hidden
        self.assertEqual(int(matte[(slice(20, None),) + front].sum()), 0)  # what stands in front never enters it
        held = [int((matte[t] & shown[t]).sum()) / int(shown[t].sum()) for t in range(66, 80)]
        self.assertGreaterEqual(min(held), 0.7, held)  # from the fourth frame after it comes out (at b578542: the seventh, 69)
        self.assertGreaterEqual(float(np.mean(held)), 0.85, held)
        print(f"comeback: from frame 66, {min(held):.2f} to {max(held):.2f} of the object, {np.mean(held):.2f} on average")


if __name__ == "__main__":
    unittest.main()
