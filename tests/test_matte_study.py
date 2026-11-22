"""tests/matte_study.py: approaches measured alike against references, on a recording that mathops.record wrote."""
import json
import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import mathops  # noqa: E402
import matte_study  # noqa: E402

N, H, W = 8, 48, 64
APPROACHES = '''
import numpy as np


def square(t):  # the edit: a square of 12 px that moves 2 px a frame
    m = np.zeros((48, 64), np.float32)
    m[14:26, 10 + 2 * t:22 + 2 * t] = 1
    return m


def perfect(rec):
    return np.stack([square(t) for t in range(rec["n"])])


def zone(rec):
    return np.repeat(np.asarray(rec["first"], np.float32).reshape(1, 48, 64), rec["n"], 0)


def half(rec):
    m = perfect(rec)
    for t in range(rec["n"]):
        m[t, :, 16 + 2 * t:] = 0
    return m


def shifted(rec):
    return np.roll(perfect(rec), 1, axis=2)


def tracked(rec):
    return rec["tracks"]["element_shot"]


def short(rec):
    return perfect(rec)[:5, ::2, ::2]


def halo(rec):  # the square, and a ring 6 to 9 px around it where the shot is the plate
    m = perfect(rec)
    for t in range(rec["n"]):
        m[t, 5:35, 1 + 2 * t:31 + 2 * t] = np.maximum(m[t, 5:35, 1 + 2 * t:31 + 2 * t], 1)
        m[t, 8:32, 4 + 2 * t:28 + 2 * t] = square(t)[8:32, 4 + 2 * t:28 + 2 * t]
    return m
'''


def square(t):
    m = np.zeros((H, W), np.float32)
    m[14:26, 10 + 2 * t:22 + 2 * t] = 1
    return m


class Study(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        d = cls.dir.name
        rng = np.random.default_rng(5)
        base = (0.3 + 0.2 * rng.random((N, H, W, 3))).astype(np.float32)
        squares = np.stack([square(t) for t in range(N)])
        shot = np.where(squares[..., None] > 0, 0.95, base).astype(np.float32)
        zone = np.zeros((1, H, W), np.float32)
        zone[0, 8:32, 4:34] = 1
        cls.rec = mathops.record(os.path.join(d, "toy"), squares, N, zone, shot, base, 1 / 16, 0.1, squares[:1], first_frame=1)
        np.savez_compressed(matte_study.beside(cls.rec, ".tracks.npz"), element_shot=(squares * 255).astype(np.uint8))
        os.makedirs(os.path.join(d, "refs", "toy"))
        for frame, t in ((1, 0), (5, 4)):
            Image.fromarray((square(t) * 255).astype(np.uint8)).save(os.path.join(d, "refs", "toy", f"ref_{frame}.png"))
        Image.fromarray(np.zeros((H, W), np.uint8)).save(os.path.join(d, "refs", "toy", "ref_8.png"))  # the object gone
        with open(os.path.join(d, "approaches.py"), "w", encoding="utf-8") as f:
            f.write(APPROACHES)
        specs = [f"{os.path.join(d, 'approaches.py')}:{fn}" for fn in ("perfect", "zone", "half", "shifted", "tracked", "short", "halo")]
        cls.out = os.path.join(d, "out")
        argv = [cls.rec, "--refs", os.path.join(d, "refs"), "--out", cls.out, "--first", "perfect", "--sheet", "--scale", "1"]
        for s in specs:
            argv += ["--approach", s]
        cls.found = matte_study.main(argv)["toy/" + os.path.basename(cls.rec)]

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_a_perfect_matte_loses_nothing(self):
        f = self.found["perfect"]
        self.assertEqual((f["edit_lost"][0], f["plate_lost"][0]), (0.0, 0.0))
        self.assertAlmostEqual(f["where_none"][0], 144 / (H * W), places=4)  # frame 8: the square where nothing is due
        self.assertEqual(f["frames"], N)

    def test_the_zone_loses_plate_and_half_a_matte_loses_half_the_edit(self):
        self.assertGreater(self.found["zone"]["plate_lost"][0], 1.0)  # the zone is several times the object
        self.assertAlmostEqual(self.found["half"]["edit_lost"][0], 0.5, places=6)
        self.assertEqual(self.found["half"]["plate_lost"][0], 0.0)

    def test_an_edge_a_pixel_away_counts_for_neither(self):
        f = self.found["shifted"]
        self.assertEqual((f["edit_lost"][0], f["plate_lost"][0]), (0.0, 0.0))

    def test_tracks_beside_the_recording_reach_the_approach(self):
        self.assertEqual(self.found["tracked"]["edit_lost"][0], 0.0)

    def test_a_smaller_shorter_matte_is_resampled_and_held(self):
        f = self.found["short"]
        self.assertLess(f["edit_lost"][0], 0.05)
        self.assertEqual(f["frames"], N)

    def test_the_baseline_runs_and_the_table_marks_what_is_worse(self):
        self.assertIn("baseline", self.found)
        with open(os.path.join(self.out, "study.md"), encoding="utf-8") as f:
            text = f.read()
        rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| ") and "---" not in line}
        self.assertTrue(rows["zone"].rstrip().endswith("| worse |"))
        self.assertTrue(rows["half"].rstrip().endswith("| worse |"))
        self.assertFalse(rows["shifted"].rstrip().endswith("| worse |"))
        self.assertIn("references on frames 1, 5, 8", text)
        with open(os.path.join(self.out, "study.json"), encoding="utf-8") as f:
            self.assertIn("per_frame", json.load(f)["toy/" + os.path.basename(self.rec)]["half"])

    def test_the_sheet_has_a_row_per_reference_and_a_column_per_approach(self):
        name = f"sheet_toy_{os.path.splitext(os.path.basename(self.rec))[0]}.jpg"
        with Image.open(os.path.join(self.out, name)) as im:
            self.assertEqual(im.size, (90 + W * (3 + 8), 28 + H * 3))

    def test_a_clean_beside_its_composite_s_recording_is_measured_with_its_clean_plate_pass(self):
        d = os.path.join(self.dir.name, "clean_case")
        rng = np.random.default_rng(9)
        base = (0.3 + 0.2 * rng.random((N, H, W, 3))).astype(np.float32)
        squares = np.stack([square(t) for t in range(N)])
        rec = mathops.record(d, squares, N, squares[:1], None, base, 1 / 16, 0.1, None)
        filled = base.copy()
        filled[:, 14:26] = 0.6  # the clean plate pass changes the rows of the squares
        mathops.record_fit(d, N, lambda i: base[i], lambda i: filled[i], squares, None, {"grow": 2})
        refs = os.path.join(self.dir.name, "clean_refs", "clean_case")
        os.makedirs(refs)
        Image.fromarray((square(4) * 255).astype(np.uint8)).save(os.path.join(refs, "ref_5.png"))
        found = matte_study.main([rec, "--refs", os.path.dirname(refs), "--out", os.path.join(self.dir.name, "clean_out")])
        f = found["clean_case/" + os.path.basename(rec)]["baseline"]
        self.assertIsNotNone(f["plate_seen"])
        self.assertLessEqual(f["plate_seen"][0], f["plate_lost"][0])

    def test_plate_lost_where_the_shot_is_the_plate_is_not_seen(self):
        f = self.found["halo"]
        self.assertGreater(f["plate_lost"][0], 0.5)  # a ring of matte 6 to 9 px around the square
        self.assertLess(f["plate_seen"][0], 0.02)  # there the shot is the plate: nothing visible is lost
        self.assertLess(self.found["zone"]["plate_seen"][0], 0.01 * self.found["zone"]["plate_lost"][0])  # the zone's plate is the shot's
        self.assertEqual(self.found["perfect"]["plate_seen"][0], 0.0)


if __name__ == "__main__":
    unittest.main()
