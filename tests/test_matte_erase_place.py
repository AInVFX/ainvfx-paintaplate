"""Follow Matte for an erase whose object comes out from behind what stands in front (matte workstream, wave 6, M7)."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


def scene(n=121, h=182, w=320):
    """horse_erase_barn in small: a camera that pans 2 px per frame, a barn that is the plate's own and stands still in
    the scene, a front object that stands still in the frame, and a tracker that finds the barn again only 6 frames
    after it comes out (12 Nov 2026: SAM found the barn again on frame 101)."""
    rng = np.random.default_rng(11)
    land = ndimage.gaussian_filter(rng.random((h, w + 2 * n, 3)).astype(np.float32), (2, 2, 0))
    land = np.clip(0.5 + 3 * (land - land.mean()), 0, 1)
    land[96:116, 213:299] = (0.62, 0.66, 0.7)  # the barn, in the plate
    base = np.stack([land[:, 2 * t:2 * t + w] for t in range(n)])
    front = (slice(30, 170), slice(60, 184))
    base[(slice(None),) + front] = (0.55, 0.25, 0.10)
    sam, shown = np.zeros((n, h, w), np.float32), np.zeros((n, h, w), bool)
    for t in range(n):
        x = 213 - 2 * t
        shown[t, 96:116, max(x, 0):max(x + 86, 0)] = True
        shown[(t,) + front] = False
        if not 77 <= t < 83:
            sam[t] = shown[t]
    return sam, shown, base, front


class ErasedPlace(unittest.TestCase):
    """An erased object stands still: where its place is in view, the matte holds it, seen by SAM or not."""

    def test_the_barn_is_in_the_matte_as_soon_as_it_comes_out(self):
        sam, shown, base, front = scene()
        out, summary = m.follow_matte(sam, len(sam), sam[0], base=base, zone=1 / 16, threshold=0.1)
        matte = out > 0.5
        hidden = [t for t in range(20, len(sam)) if not shown[t].any()]
        self.assertEqual((hidden[0], hidden[-1]), (58, 76))  # it comes out on frame 77, and SAM finds it again on 83
        self.assertEqual(int(matte[hidden].sum()), 0)  # empty while hidden
        self.assertEqual(int(matte[(slice(9, None),) + front].sum()), 0)  # what stands in front is never erased
        held = [int((matte[t] & shown[t]).sum()) / int(shown[t].sum()) for t in range(81, 83)]
        self.assertGreaterEqual(min(held), 0.6, held)  # at e347bf0: nothing until SAM is back on frame 83
        self.assertIn("an erased object stands still", summary)
        print(f"erased place: frames 81 and 82 hold {min(held):.2f} to {max(held):.2f} of the barn in view, with no mask from SAM")


if __name__ == "__main__":
    unittest.main()
