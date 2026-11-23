"""Fit to Plate's record: with PAINTAPLATE_RECORD set, fit_to_plate writes what it was given, and replay_fit reads it."""
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mathops  # noqa: E402

N, H, W = 9, 72, 128


def inputs():
    rng = np.random.default_rng(3)
    plate = rng.random((N, H, W, 3)).astype(np.float32)
    masks = np.zeros((N, 18, 32), np.float32)
    masks[:, 6:12, 10:20] = 1
    return plate, (plate * 0.9 + 0.05).astype(np.float32), masks


class FitRecord(unittest.TestCase):
    def test_every_frame_at_the_matte_s_size_and_the_reference_frames_whole(self):
        plate, gen, masks = inputs()
        keep = masks[:1] * 0.5
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"PAINTAPLATE_RECORD": d}):
            mathops.fit_to_plate(N, H, W, lambda i: plate[i], lambda i: gen[i], masks, grow=2, feather=2, keep=keep, workers=1)
            files = [f for f in os.listdir(d) if f.startswith("fit_to_plate_")]
            self.assertEqual(len(files), 1)
            self.assertIn(f"_{W}x{H}_{N}f_", files[0])
            r = mathops.replay_fit(os.path.join(d, files[0]))
        self.assertEqual(r["pick"], [0, 2, 4, 6, 8])
        self.assertEqual(r["n"], N)
        self.assertEqual((r["plate"].shape, r["image"].shape), ((N, 18, 32, 3), (N, 18, 32, 3)))
        np.testing.assert_allclose(r["spread_plate"], plate[r["pick"]], atol=1e-3)
        np.testing.assert_allclose(r["spread_image"], gen[r["pick"]], atol=1e-3)
        np.testing.assert_allclose(r["plate"][3], mathops.shrink(plate[3], 4), atol=1e-3)  # 4 x 4 blocks averaged
        np.testing.assert_array_equal(r["masks"], masks)
        np.testing.assert_allclose(r["keep"], keep, atol=1e-3)
        self.assertEqual(sorted(r["values"]), ["align", "feather", "grain", "grow", "match_color", "max_shift", "steady"])
        self.assertEqual((r["values"]["grow"], r["values"]["feather"]), (2.0, 2.0))

    def test_no_record_without_the_variable(self):
        plate, gen, masks = inputs()
        env = {k: v for k, v in os.environ.items() if k != "PAINTAPLATE_RECORD"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(mathops, "record_fit") as recorded:
            mathops.fit_to_plate(N, H, W, lambda i: plate[i], lambda i: gen[i], masks, grow=2, feather=2, workers=1)
        recorded.assert_not_called()

    def test_an_8_bit_copy_reads_from_0_to_1(self):
        plate, gen, masks = inputs()
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"PAINTAPLATE_RECORD": d}):
            path = mathops.record_fit(d, N, lambda i: plate[i], lambda i: gen[i], masks, None, {"grow": 2})
            with np.load(path) as rec:
                eight = {k: (rec[k].clip(0, 1) * 255 + 0.5).astype(np.uint8) if rec[k].dtype == np.float16 else rec[k] for k in rec.files}
            np.savez(os.path.join(d, "copy.npz"), **eight)
            r = mathops.replay_fit(os.path.join(d, "copy.npz"))
        np.testing.assert_allclose(r["spread_plate"], plate[r["pick"]], atol=1 / 255)
        np.testing.assert_array_equal(r["masks"], masks)
        self.assertIsNone(r["keep"])

    def test_reference_frames(self):
        self.assertEqual(mathops.reference_frames(121), [0, 30, 60, 90, 120])
        self.assertEqual(mathops.reference_frames(49), [0, 12, 24, 36, 48])
        self.assertEqual((mathops.reference_frames(2), mathops.reference_frames(0)), ([0, 1], []))


if __name__ == "__main__":
    unittest.main()
