"""A frame number a person reads is the plate's own: from 1 for a movie."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_live  # noqa: E402


class DecoderDifferences(unittest.TestCase):
    def test_the_first_difference_names_its_frame_from_1(self):
        a, b = [np.zeros((2, 2), np.uint8)] * 2, [np.zeros((2, 2), np.uint8), np.ones((2, 2), np.uint8)]
        pixels, comfy_live.pixels = comfy_live.pixels, lambda frames: frames
        try:
            self.assertEqual(comfy_live.differences(a, b)[3], "frame 2, sample (0, 0): 0 and 1")
            self.assertEqual(comfy_live.differences(a[:1], [np.zeros((3, 2), np.uint8)])[3], "frame 1 is (2, 2) and (3, 2)")
        finally:
            comfy_live.pixels = pixels


if __name__ == "__main__":
    unittest.main()
