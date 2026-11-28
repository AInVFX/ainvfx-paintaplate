"""mathops.with_strategy and effects_matte: how much of the shot the composite takes, on small arrays."""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mathops  # noqa: E402

N, H, W = 10, 96, 160


def box(y0, y1, x0, x1):
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = True
    return m


def busy(seed=5):
    """A plate of busy ground (leaves, grass): every pixel differs from its neighbours."""
    rng = np.random.default_rng(seed)
    return np.repeat((0.25 + 0.5 * rng.random((1, H, W, 3))).astype(np.float32), N, 0)


OBJ, HAZE, FAR, BAR = box(60, 80, 60, 84), box(20, 60, 56, 96), box(10, 30, 130, 156), box(62, 90, 86, 92)


def smoke(shot, region, frames):
    """Thin smoke: a little light and colour over the ground, on the frames given."""
    for t in frames:
        shot[t][region] = np.clip(shot[t][region] * 0.85 + 0.12, 0, 1)
    return shot


def follow(shot, base, strategy, old=None, obj=OBJ):
    sam = np.repeat(obj[None], N, 0).astype(np.float32)
    plate_masks = None if old is None else np.repeat(old[None], N, 0).astype(np.float32)
    return mathops.follow_votes(sam, sam, plate_masks, None, obj[None].astype(np.float32), shot, base, strategy=strategy)


def effects_scene():
    """An object the shot painted, thin smoke above it that comes and goes, the same smoke far away, and an old bar
    beside the object that the plate shows a little darker than the ground the shot drew in its place."""
    base = busy()
    base[:, BAR] *= 0.8
    shot = busy()
    shot[:, OBJ] = (0.9, 0.5, 0.1)
    smoke(shot, HAZE, range(0, N, 2))
    smoke(shot, FAR, range(N))
    return shot, base


class Strategy(unittest.TestCase):
    def test_object_is_follow_matte_s_matte(self):
        shot, base = effects_scene()
        m, summary = follow(shot, base, "Object", old=BAR)
        plain, _ = mathops._follow_votes(np.repeat(OBJ[None], N, 0).astype(np.float32), np.repeat(OBJ[None], N, 0).astype(np.float32),
                                         np.repeat(BAR[None], N, 0).astype(np.float32), None, OBJ[None].astype(np.float32), shot, base,
                                         0.1, 1 / 16, 1, None)
        np.testing.assert_array_equal(m, plain)
        self.assertTrue(summary.endswith("\n  Strategy: Object."))
        self.assertLess((m[0] > 0.5)[HAZE & ~OBJ].mean(), 0.05)  # thin smoke over busy ground is no change to it

    def test_object_and_effects_takes_thin_smoke_and_the_old_object_but_not_a_haze_far_away(self):
        shot, base = effects_scene()
        m, summary = follow(shot, base, "Object and effects", old=BAR)
        self.assertTrue(summary.endswith("\n  Strategy: Object and effects."))
        for t in (4, 5):  # frame 5 has no smoke: what frame 4 found holds
            self.assertTrue((m[t] > 0.5)[OBJ].all())
            self.assertGreater((m[t] > 0.5)[HAZE].mean(), 0.8)
            self.assertTrue((m[t] > 0.5)[BAR].all())
            self.assertFalse((m[t] > 0.5)[FAR].any())

    def test_whole_shot_is_every_pixel(self):
        shot, base = effects_scene()
        m, summary = follow(shot, base, "Whole shot")
        self.assertTrue((m == 1).all())
        self.assertTrue(summary.endswith("\n  Strategy: Whole shot, every pixel comes from the regenerated shot."))

    def test_auto_takes_object_and_effects_when_what_it_adds_differs_little_from_the_plate(self):
        shot, base = effects_scene()
        m, summary = follow(shot, base, "Auto", old=BAR)
        self.assertIn("\n  Strategy: Auto chose Object and effects: it barely changes the plate around the object (", summary)
        self.assertGreater((m[4] > 0.5)[HAZE].mean(), 0.8)

    def test_auto_takes_object_and_effects_when_the_edit_spreads_far(self):
        base, shot = busy(), busy()
        shot[:, OBJ] = (0.9, 0.5, 0.1)
        shot[:, :, 120:] = 0.1  # the edit darkened the far quarter of the frame
        m, summary = follow(shot, base, "Auto")
        self.assertRegex(summary, r"\n  Strategy: Auto chose Object and effects: the edit spreads past the object \(\d+% of the frame\)\.$")

    def test_auto_keeps_object_when_object_and_effects_would_give_up_plate_that_differs(self):
        base, shot = busy(), busy(seed=6)  # the shot drew other ground all around the object, within reach of it
        shot[:, :, :] = base
        ring = box(40, 96, 36, 108)
        shot[:, ring] = busy(seed=6)[:, ring]
        shot[:, OBJ] = (0.9, 0.5, 0.1)
        m, summary = follow(shot, base, "Auto")
        self.assertRegex(summary, r"\n  Strategy: Auto chose Object: Object and effects would change \d+% of the frame around the object\.$")
        plain, _ = follow(shot, base, "Object")
        np.testing.assert_array_equal(m, plain)

    def test_a_clean_runs_object_for_auto(self):
        zone = np.repeat(OBJ[None], N, 0).astype(np.float32)
        m, summary = mathops.clean_votes(zone, None, None, OBJ[None].astype(np.float32), strategy="Auto")
        plain, _ = mathops.clean_votes(zone, None, None, OBJ[None].astype(np.float32))
        np.testing.assert_array_equal(m, plain)
        self.assertTrue(summary.endswith("\n  Strategy: Auto chose Object: a Clean keeps to its object."))

    def test_an_unknown_strategy_stops(self):
        shot, base = effects_scene()
        with self.assertRaises(ValueError):
            follow(shot, base, "Wider")

    def test_a_recording_keeps_its_strategy_and_an_older_one_replays_as_object(self):
        shot, base = effects_scene()
        sam = np.repeat(OBJ[None], N, 0).astype(np.float32)
        with tempfile.TemporaryDirectory() as d:
            path = mathops.record_votes(d, "paint", strategy="Object and effects", shot_masks=sam, word_masks=None, plate_masks=None,
                                        kept=None, element=sam[:1], shot=shot, base=base, threshold=0.1, zone=1 / 16, first_frame=1)
            self.assertEqual(mathops.replay_votes(path)["args"]["strategy"], "Object and effects")
            older = os.path.join(d, "older.npz")
            np.savez_compressed(older, **{k: v for k, v in np.load(path).items() if k != "strategy"})
            self.assertEqual(mathops.replay_votes(older)["args"]["strategy"], "Object")


if __name__ == "__main__":
    unittest.main()
