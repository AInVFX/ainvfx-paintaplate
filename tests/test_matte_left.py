"""Follow Matte for a painted object that LTX walks out of its place, in view, on a plate that stands still. Joined frame
after frame to the matte of the frame before, it keeps its matte, and a change that LTX leaves at the empty place stays
out; when it walks back, the matte comes back with it. The tracker's mask counts as the paint zone only when it lies
mostly inside it."""
import os
import re
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mathops  # noqa: E402

H, W, N = 64, 160, 40


def shot_of(path, residue=None):
    """A static plate; the painted square at column path[t] on frame t (12 x 12 px from column 40 at first); from frame
    `residue` on, a 4 x 4 change that LTX leaves at the square's first place."""
    plate = np.clip(0.5 + 0.06 * np.random.default_rng(5).standard_normal((H, W, 3)), 0, 1).astype(np.float32)
    base, shot, sam = np.repeat(plate[None], N, 0), np.repeat(plate[None], N, 0), np.zeros((N, H, W), np.float32)
    for t, x in enumerate(path):
        shot[t, 26:38, x:x + 12], sam[t, 26:38, x:x + 12] = 0.05, 1
        if residue is not None and t >= residue:
            shot[t, 30:34, 44:48] = 0.25
    first = np.zeros((1, H, W), np.float32)
    first[0, 26:38, 40:52] = 1
    return dict(masks=sam, n=N, first=first, shot=shot, base=base)


class LeftItsPlace(unittest.TestCase):
    def test_an_object_that_walks_out_of_its_place_in_view_keeps_its_matte(self):
        path = [40 if t < 14 else min(40 + 6 * (t - 13), W - 12) for t in range(N)]
        matte, summary = mathops.follow_matte(**shot_of(path, residue=24))
        self.assertNotIn("left its place", summary)
        self.assertIn("\n  Object moves from frame ", summary)
        for t, x in enumerate(path):
            self.assertTrue((matte[t, 26:38, x:x + 12] > 0.5).all(), f"frame {t}: the object is in the matte\n{summary}")
        self.assertEqual(int((matte[24:, 30:34, 44:48] > 0.5).sum()), 0)  # the change left at the empty place stays out

    def test_comeback_keeps_the_matte(self):
        path = [40 if t < 14 else 40 + 6 * min(t - 13, 6) if t < 26 else max(76 - 6 * (t - 25), 40) for t in range(N)]
        matte, summary = mathops.follow_matte(**shot_of(path))
        self.assertNotIn("left its place", summary)
        self.assertTrue((matte[-1, 26:38, 40:52] > 0.5).all())


class ZoneInside(unittest.TestCase):
    def test_a_large_mask_away_from_the_zone_is_not_the_zone(self):
        def run(blob):
            plate = np.clip(0.5 + 0.06 * np.random.default_rng(6).standard_normal((H, W, 3)), 0, 1).astype(np.float32)
            base, shot = np.repeat(plate[None], N, 0), np.repeat(plate[None], N, 0)
            shot[:, 27:37, 45:55] = 0.05
            zone, element, sam = np.zeros((1, H, W), np.float32), np.zeros((1, H, W), np.float32), np.zeros((N, H, W), np.float32)
            zone[0, 17:47, 30:70], element[0, 27:37, 45:55] = 1, 1
            sam[:5, 17:47, 30:70], sam[5:, 27:37, 45:55] = 1, 1  # the zone on its first frames, then the object
            if blob:
                sam[25:, 10:50, 100:150] = 1  # then also a large mask far from the zone
            _, summary = mathops.follow_matte(sam, N, zone, shot, base, element=element)
            return int(re.search(r"paint zone outside the object's place, on (\d+) frames?", summary)[1])
        self.assertEqual(run(True), run(False))


if __name__ == "__main__":
    unittest.main()
