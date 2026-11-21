"""Follow Matte for a painted object that keeps its place over its first frames, then moves with what it is attached
to: two beams that turn about the point they leave from, as beams from a head that turns, or a compact object that
slides away. The matte follows what the shot shows. An object that the shot still shows, joined frame after frame to
the matte of the frame before, keeps its matte when it leaves the place where it stood, whether the tracker sees it or
loses it, and the summary does not warn. An object that never moves keeps its place, one that moves from the first
frame is followed, and the matte of an object that the shot stops showing ends with it."""
import os
import sys
import unittest

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mathops  # noqa: E402

N, H, W = 48, 180, 320
STILL = 12  # frames before the object moves: more than mathops.FOLLOW_STILL


def scene(kind="beams", still=STILL, turn=1.2, step=3.0, seen=15, stop=None):
    """A textured plate that stands still, and a painted object that keeps its place for `still` frames, then moves.
    kind "beams": two bright beams 7 px wide that leave one point towards the right edge and the bottom, and turn about
    it by `turn` degrees a frame. kind "blob": a compact object 28 x 18 px that moves left by `step` px a frame. The
    tracker returns the object on its first `seen` frames, after a paint zone grown 6 px around it. From frame `stop`
    on, the shot no longer draws the object. Returns follow_matte's arguments, and where the shot draws the object on
    each frame."""
    rng = np.random.default_rng(5)
    plate = (ndimage.gaussian_filter(rng.random((H, W, 3)), (1.2, 1.2, 0)) * 0.5 + 0.2).astype(np.float32)
    base = np.repeat(plate[None], N, 0)
    yy, xx = np.mgrid[:H, :W]

    def shape(t):
        moved = max(0, t - still)
        if kind == "blob":
            return ((xx - (220 - step * moved)) / 14.0) ** 2 + ((yy - 90) / 9.0) ** 2 <= 1
        m = np.zeros((H, W), bool)
        for angle in (14.0, 38.0):
            a = np.deg2rad(angle + turn * moved)
            along, across = (xx - 150) * np.cos(a) + (yy - 50) * np.sin(a), -(xx - 150) * np.sin(a) + (yy - 50) * np.cos(a)
            m |= (np.abs(across) < 3.5) & (along >= 0)
        return m
    shown = np.stack([shape(t) for t in range(N)])
    if stop is not None:
        shown[stop:] = False
    shot = base.copy()
    shot[shown] = (0.95, 0.15, 0.15)
    masks = shown.astype(np.float32)
    masks[seen:] = 0
    zone = ndimage.binary_dilation(shown[0], iterations=6).astype(np.float32)
    return dict(masks=masks, n=N, first=zone, shot=shot, base=base, element=shown[0].astype(np.float32)), shown


class MovesAfterStandingStill(unittest.TestCase):
    def follows(self, args, shown, label):
        """The matte holds the object on every frame where the shot shows it, and little beside it."""
        mattes, summary = mathops.follow_matte(**args, workers=1)
        got = mattes > 0.5
        for t in range(N):
            if shown[t].any():
                area = int(shown[t].sum())
                self.assertGreaterEqual(int((got[t] & shown[t]).sum()), 0.9 * area, f"{label}, frame {t}: the object is in the matte\n{summary}")
                beside = got[t] & ~ndimage.binary_dilation(shown[t], iterations=4)
                self.assertLessEqual(int(beside.sum()), 0.25 * area, f"{label}, frame {t}: little of the matte lies beside the object\n{summary}")
        return summary

    def test_beams_that_turn_after_standing_still_keep_their_matte(self):
        for seen in (15, N):
            with self.subTest(seen=seen):
                summary = self.follows(*scene("beams", seen=seen), f"beams, tracked on {seen} frames")
                self.assertNotIn("Warning", summary)

    def test_an_object_that_slides_away_after_standing_still_keeps_its_matte(self):
        for seen in (15, N):
            with self.subTest(seen=seen):
                summary = self.follows(*scene("blob", seen=seen), f"blob, tracked on {seen} frames")
                self.assertNotIn("Warning", summary)

    def test_an_object_that_never_moves_keeps_its_place(self):
        for kind, kw in (("beams", {"turn": 0.0}), ("blob", {"step": 0.0})):
            with self.subTest(kind=kind):
                summary = self.follows(*scene(kind, **kw), f"{kind} that never moves")
                self.assertNotIn("Warning", summary)
                self.assertNotIn("Object moves from frame", summary)

    def test_an_object_that_moves_from_the_first_frame_is_followed(self):
        for kind in ("beams", "blob"):
            with self.subTest(kind=kind):
                summary = self.follows(*scene(kind, still=0), f"{kind} that moves from the first frame")
                self.assertNotIn("Warning", summary)
                self.assertIn("\n  Object moves from frame ", summary)

    def test_the_matte_of_an_object_that_the_shot_stops_showing_ends_with_it(self):
        for label, kw in (("the shot stops drawing it at frame 30", {"stop": 30}), ("it leaves the frame", {"step": 8.0})):
            with self.subTest(label):
                args, shown = scene("blob", **kw)
                mattes, summary = mathops.follow_matte(**args, workers=1)
                gone = np.flatnonzero(~shown.reshape(N, -1).any(1))
                self.assertGreater(len(gone), 3, label)
                for t in gone:
                    self.assertEqual(int((mattes[t] > 0.5).sum()), 0, f"{label}, frame {t}: the matte ends with the object\n{summary}")


if __name__ == "__main__":
    unittest.main()
