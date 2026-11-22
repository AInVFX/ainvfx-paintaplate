"""mathops.follow_votes: a paint's matte from SAM 3.1's answers, judged by how much the shot changed, on small arrays."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mathops  # noqa: E402

N, H, W = 10, 48, 96


def scene(seed=1):
    rng = np.random.default_rng(seed)
    return (0.3 + 0.2 * rng.random((N, H, W, 3))).astype(np.float32)


def box(t0, t1, y0, y1, x0, x1, n=N):
    m = np.zeros((n, H, W), np.float32)
    m[t0:t1, y0:y1, x0:x1] = 1
    return m


def paint(base, mask, value=0.95):
    return np.where(mask[..., None] > 0, value, base).astype(np.float32)


class Votes(unittest.TestCase):
    def test_a_new_object_is_whole_and_a_jump_far_away_is_left_out(self):
        base = scene()
        obj = np.zeros((N, H, W), np.float32)
        for t in range(N):
            obj[t, 16:28, 10 + 2 * t:24 + 2 * t] = 1
        far = box(5, 6, 30, 44, 76, 92)
        shot = paint(paint(base, obj), far, 0.1)  # the far piece changed too: only its place gives it away
        m, summary = mathops.follow_votes(obj + far, obj, None, None, obj[:1], shot, base)
        self.assertTrue((m[5] > 0.5)[obj[5] > 0].all())
        self.assertFalse((m[5] > 0.5)[far[5] > 0].any())
        self.assertIn("\n  Left out: SAM masks away from the object, on 1 frame.", summary)

    def test_a_mask_over_what_the_plate_keeps(self):
        base = scene(2)
        horse = box(0, N, 8, 40, 20, 70)
        patch = box(0, N, 20, 30, 30, 50)  # the paint changed this part of the horse
        shot = paint(base, patch)
        m, summary = mathops.follow_votes(horse, horse, None, horse, patch[:1], shot, base)
        held = m > 0.5
        self.assertTrue(held[3][patch[3] > 0].mean() > 0.9)
        self.assertFalse(held[3][(horse[3] > 0) & (mathops.dilate(patch[3].astype(np.uint8), 4) == 0)].any())
        self.assertIn("Cut to the change: SAM masks over what the plate keeps", summary)
        m2, _ = mathops.follow_votes(horse, horse, None, horse, patch[:1], base.copy(), base)  # nothing changed
        self.assertFalse((m2[3:] > 0.5).any())

    def test_an_object_hidden_behind_what_the_plate_keeps_comes_back(self):
        base = scene(3)
        horse = box(0, N, 4, 44, 40, 70)
        cow = box(0, 3, 14, 26, 24, 38) + box(7, N, 14, 26, 74, 88)
        answers = cow + box(3, 7, 14, 26, 44, 58)  # while hidden, SAM sits on the horse
        shot = paint(base, cow)
        m, summary = mathops.follow_votes(answers, answers, None, horse, cow[:1], shot, base, zone=1 / 8)
        self.assertFalse((m[3:7] > 0.5).any())
        self.assertTrue((m[8] > 0.5)[cow[8] > 0].mean() > 0.9)
        self.assertIn("\n  Object hidden from frame 4 to 7.", summary)

    def test_nothing_new_once_the_object_has_left_the_frame(self):
        base = scene(4)
        whale = np.zeros((N, H, W), np.float32)
        for t in range(4):
            whale[t, 20:32, 70 + 8 * t:min(W, 90 + 8 * t)] = 1
        wake = box(6, N, 30, 46, 30, 60)
        shot = paint(paint(base, whale), wake, 0.1)
        m, summary = mathops.follow_votes(whale + wake, whale + wake, None, None, whale[:1], shot, base)
        self.assertFalse((m[6:] > 0.5).any())
        self.assertIn("\n  Object out of the frame from frame 5.", summary)

    def test_the_old_object_joins_where_the_shot_changed_near_the_new_one(self):
        base = scene(5)
        new = box(0, N, 16, 30, 20, 40)
        old = box(0, N, 12, 34, 16, 46)  # the brace the new arm replaces: larger than it
        stray = box(0, N, 36, 46, 80, 92)  # the plate's mask drifting onto another thing
        shot = paint(paint(base, old, 0.2), new)
        m, summary = mathops.follow_votes(new, new, old + stray, None, new[:1], shot, base)
        self.assertTrue((m[4] > 0.5)[old[4] > 0].mean() > 0.9)
        self.assertFalse((m[4] > 0.5)[stray[4] > 0].any())
        self.assertIn("\n  Old object added where the shot changed, on 10 frames.", summary)

    def test_the_edit_s_own_subject_is_not_a_kept_thing(self):
        objects = np.zeros((N, 2, H, W), np.float32)
        objects[:, 0, 10:30, 10:30] = 1  # inside the area the edit works on: the barn a Clean removes
        objects[:, 1, 10:40, 50:80] = 1  # outside it: the horse
        region = box(0, 1, 5, 35, 5, 35)[0] > 0
        kept = mathops.kept_things(objects, region)
        self.assertFalse(kept[0, 20, 20])
        self.assertTrue(kept[0, 20, 60])

    def test_the_first_frame_takes_the_second_frame_s_answer(self):
        base = scene(6)
        obj = box(0, N, 18, 30, 30, 46)
        echo = obj.copy()
        echo[0] = box(0, 1, 4, 44, 10, 70)[0]  # on its first frame SAM answers with its prompt
        shot = paint(base, obj)
        m, _ = mathops.follow_votes(echo, obj, None, None, obj[:1], shot, base)
        self.assertLess((m[0] > 0.5).sum(), 1.5 * obj[0].sum())


    def test_a_clean_leaves_out_what_the_plate_keeps(self):
        zone = box(0, 1, 4, 30, 50, 96)[0]
        palm = box(0, N, 6, 28, 56, 94)  # the removed thing
        lady = box(0, N, 10, 46, 40, 66)  # in front of the palm's left side
        track = palm.copy()
        track[0] = zone  # on its first frame SAM answers with the zone
        named = np.stack([palm, box(0, N, 40, 46, 2, 10)], axis=1)  # the palm, and a plant elsewhere with the same name
        kept = mathops.kept_things(np.stack([lady, palm], axis=1), zone > 0)  # the palm lies in the zone: not kept
        m, summary = mathops.clean_votes(track, named, kept, zone)
        self.assertFalse((m > 0.5)[lady > 0].any())
        self.assertTrue((m[3] > 0.5)[(palm[3] > 0) & (lady[3] == 0)].all())
        self.assertFalse((m[0] > 0.5)[(zone > 0) & (palm[0] == 0)].any())  # the first frame is the palm, not the zone
        self.assertEqual(summary, "tracked on 10 of 10 frames.\n  Left out: what the plate keeps, on 10 frames.")


    def test_sam_s_words_from_the_upsampler_s_answers(self):
        self.assertEqual(mathops.sam_words("Bald eagle landing on the fence post with wings spread wide."), "bald eagle")
        self.assertEqual(mathops.sam_words("palm branches and fronds outside the open window, including the large fronds"), "palm branches and fronds")
        self.assertEqual(mathops.sam_words("two red laser beams"), "two red laser beams")
        kept = "person, prosthetic arm apparatus, blue-sleeved arm, no other people, animals, or vehicles visible"
        self.assertEqual(mathops.sam_words(kept, "kept"), "person, prosthetic arm apparatus, blue-sleeved arm, animals")
        self.assertEqual(mathops.sam_words("None.", "kept"), "")


if __name__ == "__main__":
    unittest.main()
