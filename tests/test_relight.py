"""A light edit's shade strokes: Relight Transfer darkens the frame there, in linear light."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mathops  # noqa: E402


class Shade(unittest.TestCase):
    def test_darkens_only_where_painted_in_linear_light(self):
        img = np.full((4, 4, 3), 0.5, np.float32)
        shade = np.zeros((4, 4), np.float32); shade[:, :2] = 1.0
        out = mathops.shade_frame(img, shade, 0.7, "linear")
        self.assertTrue(np.allclose(out[:, :2], 0.15) and np.allclose(out[:, 2:], 0.5))

    def test_srgb_frames_are_darkened_through_linear_light(self):
        img = np.full((2, 2, 3), 0.5, np.float32)
        out = mathops.shade_frame(img, np.ones((2, 2), np.float32), 0.5, "sRGB")
        self.assertTrue(np.allclose(out, mathops.linear_to_srgb(mathops.srgb_to_linear(img) * 0.5), atol=1e-6))

    def test_a_smaller_shade_is_fitted_to_the_frame(self):
        out = mathops.shade_frame(np.ones((8, 8, 3), np.float32), np.ones((2, 2), np.float32), 1.0)
        self.assertEqual(out.shape, (8, 8, 3)); self.assertTrue(np.allclose(out, 0))


if __name__ == "__main__":
    unittest.main()
