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


def specks_scene():
    """The body at 480 x 240, where a zone is 30 px: the shot changes a patch of it; beside the patch, 2 px below it, a
    thin piece changes too, as a leg seen between the rails of a fence; and 4 x 4 specks of change lie on the body far
    from the patch, as a regenerated frame makes where it differs a little more than the threshold."""
    n, h, w = 6, 240, 480
    rng = np.random.default_rng(11)
    field = 0.45 + 0.1 * rng.random((h, w, 3), np.float32)
    base, shot = np.repeat(field[None], n, 0), np.repeat(field[None], n, 0)
    masks, specks, piece = np.zeros((n, h, w), np.float32), np.zeros((n, h, w), bool), np.zeros((n, h, w), bool)
    for t in range(n):
        x = 60 + 4 * t
        for img in (base, shot):
            img[t, 60:180, x:x + 300] = (0.45, 0.25, 0.12)
        masks[t, 60:180, x:x + 300] = 1
        shot[t, 100:150, x + 100:x + 160] = (0.75, 0.75, 0.8)
        shot[t, 152:172, x + 128:x + 132] = (0.75, 0.75, 0.8)
        piece[t, 152:172, x + 128:x + 132] = True
        for sy, sx in ((64, 250), (160, 280), (90, 330), (165, 20)):
            shot[t, sy:sy + 4, x + sx:x + sx + 4] = (0.75, 0.25, 0.12)
            specks[t, sy:sy + 4, x + sx:x + sx + 4] = True
    first = np.zeros((h, w), np.float32)
    first[95:175, 155:225] = 1
    element = (np.abs(shot[0] - base[0]).max(-1) > 0.05).astype(np.float32) * (first > 0)
    return dict(masks=masks, n=n, first=first, shot=shot, base=base, element=element), specks, piece


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


    def test_specks_far_from_the_change_stay_out_and_a_piece_beside_it_stays_in(self):
        args, specks, piece = specks_scene()
        mattes, _ = mathops.follow_matte(**args, workers=1)
        for t in range(args["n"]):
            x = 60 + 4 * t
            self.assertGreater(mattes[t][100:150, x + 100:x + 160].mean(), 0.9, f"frame {t}: the changed patch is in the matte")
            self.assertGreater(mattes[t][piece[t]].mean(), 0.9, f"frame {t}: the thin piece beside the patch is in the matte")
            self.assertEqual(float(mattes[t][specks[t]].max()), 0.0, f"frame {t}: the specks far from the patch are out of the matte")


    def test_a_frame_with_no_change_holds_the_matte_before(self):
        args = scene(whole_changed=False)
        for t in (4, 5):  # the shot shows no change on these frames: the tracker still returns the whole body
            args["shot"][t] = args["base"][t]
        mattes, _ = mathops.follow_matte(**args, workers=1)
        for t in (4, 5):
            x = 10 + 3 * t
            body, part = np.zeros((H, W), bool), np.zeros((H, W), bool)
            body[20:56, x:x + 80], part[34:48, x + 30:x + 46] = True, True
            far = body & ~mathops.dilate(part.astype(np.uint8), 8).astype(bool)
            self.assertLess(mattes[t][far].mean(), 0.05, f"frame {t}: no flash of the whole body")
            self.assertGreater(mattes[t][part].mean(), 0.5, f"frame {t}: the matte before holds where the part is")


if __name__ == "__main__":
    unittest.main()
