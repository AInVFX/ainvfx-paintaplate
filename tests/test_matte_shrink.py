"""Follow Matte while the tracker's mask shrinks from the paint zone to the object over several frames."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402

# SAM's mask against the object on the frames before it finds the object, from a bald eagle painted in a zone 6.3 times
# its size: on the last two, under two fifths of the zone, it is still more than twice the object
RATIOS = [6.3, 5.6, 5.6, 5.4, 5.0, 4.7, 3.65, 2.86, 2.31, 2.45]


def scene(n=24, h=72, w=128, grown=(), wing=()):
    """A camera that pans 1 px per frame, an object that stands still in the scene, painted in a zone 6.3 times its
    size, and a tracker whose mask shrinks from the zone to the object over 10 frames; on the frames `grown`, after it
    found the object, the object grows to 2.4 times its size in the shot, and the tracker's mask with it; on the frames `wing`, the shot shows a wing that opens out of
    the object's place, joined to it. Returns the wing's pixels too."""
    rng = np.random.default_rng(7)
    wide = (ndimage.gaussian_filter(rng.random((h, w + n, 3)), (0.7, 0.7, 0)) * 0.6 + 0.2).astype(np.float32)
    base = np.stack([wide[:, t:t + w] for t in range(n)])
    yy, xx = np.mgrid[:h, :w]

    def ellipse(t, ratio):  # the object's ellipse at frame t, its area times `ratio`
        return ((xx - (70 - t)) / (10.0 * ratio ** 0.5)) ** 2 + ((yy - 36) / (7.0 * ratio ** 0.5)) ** 2 <= 1
    obj = np.stack([ellipse(t, 1) for t in range(n)])
    shot = base.copy()
    shot[obj] = (0.95, 0.9, 0.85)
    wings = np.zeros_like(obj)
    for t in wing:
        wings[t, 31:37, 78 - t:86 - t] = ~obj[t, 31:37, 78 - t:86 - t]
    shot[wings] = (0.95, 0.9, 0.85)
    for t in grown:
        shot[t][ellipse(t, 2.4)] = (0.95, 0.9, 0.85)
    sam = np.stack([ellipse(t, RATIOS[t]) if t < len(RATIOS) else ellipse(t, 2.4) if t in grown else obj[t] for t in range(n)])
    return sam.astype(np.float32), obj, shot, base, wings


class Shrink(unittest.TestCase):
    def test_the_matte_holds_the_object_while_the_tracker_shrinks_from_the_zone(self):
        sam, obj, shot, base, _ = scene()
        out, summary = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, element=obj[0].astype(np.float32))
        matte = out > 0.5
        areas, tight = matte.reshape(len(matte), -1).sum(1), int(obj[0].sum())
        self.assertLessEqual(int(areas[:12].max()), 1.5 * tight, areas[:12])
        for t in range(len(sam)):  # and the object is in the matte on every frame
            self.assertGreaterEqual(int((matte[t] & obj[t]).sum()), 0.95 * int(obj[t].sum()), t)
        self.assertIn("(SAM mask held the paint zone).", summary)

    def test_a_mask_that_grows_after_the_object_was_found_is_kept(self):
        sam, obj, shot, base, _ = scene(grown=(15, 16))
        out, _ = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, element=obj[0].astype(np.float32))
        for t in (15, 16):
            grown = sam[t] > 0.5
            self.assertGreaterEqual(int(((out[t] > 0.5) & grown).sum()), 0.9 * int(grown.sum()), t)


    def test_a_part_that_moves_out_of_the_place_stays_in_the_held_frames(self):
        sam, obj, shot, base, wings = scene(wing=(6, 7, 8, 9))
        out, _ = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, element=obj[0].astype(np.float32))
        matte = out > 0.5
        for t in (6, 7, 8, 9):  # the tracker still shrinks from the zone there: the matte holds the place and the wing
            self.assertGreaterEqual(int((matte[t] & wings[t]).sum()), 0.9 * int(wings[t].sum()), t)
            self.assertLessEqual(int(matte[t].sum()), 1.5 * int((obj[t] | wings[t]).sum()), t)

if __name__ == "__main__":
    unittest.main()
