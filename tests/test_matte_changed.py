"""A paint's matte keeps, of the object the tracker follows, what the shot changed and what joins it to the object's
region. The tracker can return a whole object for a paint on a small part of it (SAM 3.1 returns a whole horse for a
paint on its body); a part of that object which the shot left as the plate goes back to the plate."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mathops  # noqa: E402

N, H, W = 10, 72, 144


def scene(whole_changed):
    """A grey textured field, and a brown body that walks right by 3 px a frame. The tracker returns the whole body on
    every frame. The shot changes a small patch of the body (a robot part), or the whole body."""
    rng = np.random.default_rng(7)
    field = 0.45 + 0.1 * rng.random((H, W, 3), np.float32)
    base, shot = np.repeat(field[None], N, 0), np.repeat(field[None], N, 0)
    masks = np.zeros((N, H, W), np.float32)
    for t in range(N):
        x = 10 + 3 * t
        base[t, 20:56, x:x + 80] = (0.45, 0.25, 0.12)
        shot[t, 20:56, x:x + 80] = (0.45, 0.25, 0.12)
        masks[t, 20:56, x:x + 80] = 1
        if whole_changed:
            shot[t, 20:56, x:x + 80] = (0.75, 0.75, 0.8)
        else:
            shot[t, 34:48, x + 30:x + 46] = (0.75, 0.75, 0.8)
    first = np.zeros((H, W), np.float32)
    first[30:52, 36:60] = 1  # the painted zone on frame 0, a little wider than the part
    element = (np.abs(shot[0] - base[0]).max(-1) > 0.05).astype(np.float32)
    return dict(masks=masks, n=N, first=first, shot=shot, base=base, element=element)


class TestMatteChanged(unittest.TestCase):
    def test_a_part_left_as_the_plate_goes_back_to_it(self):
        mattes, _ = mathops.follow_matte(**scene(whole_changed=False), workers=1)
        for t in (0, N // 2, N - 1):
            x = 10 + 3 * t
            body, part = np.zeros((H, W), bool), np.zeros((H, W), bool)
            body[20:56, x:x + 80], part[34:48, x + 30:x + 46] = True, True
            self.assertGreater(mattes[t][part].mean(), 0.9, f"frame {t}: the changed part is in the matte")
            far = body & ~mathops.dilate(part.astype(np.uint8), 8).astype(bool)
            self.assertLess(mattes[t][far].mean(), 0.05, f"frame {t}: the body the shot left as the plate is out of the matte")

    def test_an_object_the_shot_changed_whole_stays_whole(self):
        mattes, _ = mathops.follow_matte(**scene(whole_changed=True), workers=1)
        for t in (N // 2, N - 1):
            x = 10 + 3 * t
            body = np.zeros((H, W), bool)
            body[20:56, x:x + 80] = True
            self.assertGreater(mattes[t][body].mean(), 0.95, f"frame {t}: the whole changed body is in the matte")


if __name__ == "__main__":
    unittest.main()
