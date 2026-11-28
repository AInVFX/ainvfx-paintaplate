"""mathops.seam_field on a fluid shot: smoke on pure black, and a shot whose black is a little green. The colour field at
the matte's edge keeps the exposure fix and adds no tint, where the ratio of two near-zero values would tint the smoke's edge magenta."""
import os
import sys
import unittest

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mathops  # noqa: E402

H, W = 128, 240


def smoke_on_black():
    rng = np.random.default_rng(3)
    cloud = ndimage.gaussian_filter(rng.random((H, W)), 6)
    cloud = np.clip((cloud - cloud.mean()) * 40 + 0.35, 0, 0.9)
    cloud[:, :60] = 0.0  # black beside the smoke, as a fluid shot has it
    cloud[:, 180:] = 0.0
    return np.repeat(cloud[..., None], 3, -1).astype(np.float32)


class SeamDark(unittest.TestCase):
    def test_a_green_black_in_the_shot_adds_no_tint_and_the_exposure_fix_stays(self):
        plate = smoke_on_black()
        luma = plate @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        gen = plate * 1.03
        dark = luma < 0.08
        gen[dark] += np.array([0.004, 0.012, 0.004], np.float32)  # the shot's black, a little green
        yy, xx = np.mgrid[:H, :W]
        mask = ((((yy - 64) / 40) ** 2 + ((xx - 120) / 70) ** 2) < 1).astype(np.float32)
        field = mathops.seam_field(plate, gen, mask, 5.0)
        tint = np.abs((field[..., 0] + field[..., 2]) / 2 - field[..., 1])
        self.assertLess(float(tint.max()), 0.01)
        self.assertAlmostEqual(float(field[mask > 0.5].mean()), float(np.log(1 / 1.03)), delta=0.01)

    def test_an_edge_in_the_black_alone_has_no_field(self):
        plate = np.zeros((H, W, 3), np.float32)
        gen = plate + np.array([0.004, 0.012, 0.004], np.float32)
        mask = np.zeros((H, W), np.float32)
        mask[40:80, 80:160] = 1
        self.assertEqual(float(np.abs(mathops.seam_field(plate, gen, mask, 5.0)).max()), 0.0)


if __name__ == "__main__":
    unittest.main()
