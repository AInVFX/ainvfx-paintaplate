"""Follow Matte for an erase whose object drives away from its first place, inside a zone larger than itself."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402

TOP, LEFT, TALL, LONG = 100, 24, 20, 48  # the car on frame 0
ZONE = (slice(84, 140), slice(12, 96))  # the stroke's zone: the first-frame mask SAM is given, about 5 times the car


def left_at(t):
    """The car's left edge: 1 px a frame up to frame 8, so it keeps its place until FOLLOW_STILL, then 2 px a frame."""
    return LEFT + min(t, 8) + 2 * max(t - 8, 0)


def scene(n=121, h=176, w=320):
    """A still camera over a textured road, and a textured car that is the plate's own. SAM is given the stroke's zone
    and returns the car itself on every frame."""
    rng = np.random.default_rng(22)
    road = ndimage.gaussian_filter(rng.random((h, w, 3)).astype(np.float32), (2, 2, 0))
    road = np.clip(0.45 + 2 * (road - road.mean()), 0, 1)
    paint = ndimage.gaussian_filter(rng.random((TALL, LONG)).astype(np.float32), 1.5)
    body = np.clip(0.3 + 4 * (paint - paint.mean()), 0.05, 1)[..., None] * np.float32((1.0, 0.5, 0.15))  # its texture moves with it
    base, sam = np.repeat(road[None], n, 0), np.zeros((n, h, w), np.float32)
    for t in range(n):
        car = (slice(TOP, TOP + TALL), slice(left_at(t), left_at(t) + LONG))
        base[(t,) + car], sam[(t,) + car] = body, 1.0
    first = np.zeros((h, w), np.float32)
    first[ZONE] = 1.0
    return sam, first, base


class ErasedObjectLeaves(unittest.TestCase):
    """An erased object that keeps its place over the first frames, then leaves it: the matte follows SAM's mask, and
    the place it left is no longer in the matte. Its zone is so much larger than itself that the object never covers a
    quarter of it: that was no reason to judge SAM's mask to be what stands in front."""

    def test_the_matte_follows_the_car_and_leaves_its_first_place(self):
        sam, first, base = scene()
        out, summary = m.follow_matte(sam, len(sam), first, base=base, zone=1 / 16, threshold=0.1)
        matte, car = out > 0.5, sam > 0.5
        held = [int((matte[t] & car[t]).sum()) / int(car[t].sum()) for t in range(len(sam))]
        self.assertGreaterEqual(min(held), 0.95, f"least share of the car in the matte: {min(held):.2f} at frame {int(np.argmin(held))}")
        gone = [t for t in range(len(sam)) if not (car[t] & car[0]).any()]  # the frames where the car has left its first place
        self.assertEqual(gone[0], 28)
        self.assertEqual(int((matte[gone] & car[0]).sum()), 0)  # nothing of that place stays in the matte
        self.assertTrue(summary.startswith(f"tracked on {len(sam)} of {len(sam)} frames."), summary)
        self.assertIn("\n  Object moves from frame ", summary)
        self.assertNotIn("Object stands still", summary)
        print(f"erase away: the car holds {min(held):.2f} or more of its own matte on every frame; {summary.splitlines()[0]}")


if __name__ == "__main__":
    unittest.main()
