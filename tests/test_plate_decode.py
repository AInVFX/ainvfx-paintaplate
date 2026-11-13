"""PL7: our decoder without torch. A movie: the trim, the 8k+1 padding, the 8-bit path with alpha, 10 bits and a width
that is not a multiple of 32. An image sequence: each file in its place, half floats above 1.0, alpha that must hold for
every file. Its pictures against core's: tests/decode_parity.py, which tests/comfy_live.py runs."""
import os
import sys
import tempfile
import unittest

from _env import ROOT, require

require("numpy", "av", "OpenEXR", "PIL")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import av  # noqa: E402
import numpy as np  # noqa: E402
import decode_parity  # noqa: E402
import plateio  # noqa: E402
from PIL import Image  # noqa: E402


class Decode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.paths = {os.path.basename(p): p for p in decode_parity.movies(cls.tmp.name)}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_trim_and_the_padding_in_the_same_array(self):
        rgb, alpha, n = plateio.decode_video(self.paths["h264_256.mp4"], 20, 24.0, pad_8n1=True)
        self.assertEqual((n, rgb.shape), (20, (25, 144, 256, 3)))
        self.assertIsNone(alpha)
        self.assertTrue((rgb[20:] == rgb[19]).all())
        rgb, _, n = plateio.decode_video(self.paths["h264_256.mp4"], 121, 24.0)
        self.assertEqual((n, rgb.shape[0]), (30, 30))

    def test_eight_bits_with_alpha_are_the_values_over_255(self):
        path = self.paths["png_rgba.mov"]
        rgb, alpha, n = plateio.decode_video(path, 5, 24.0)
        with av.open(path) as c:
            first = next(c.decode(video=0)).to_ndarray(format="rgba").astype(np.float32)
        self.assertEqual(rgb[0].tobytes(), (first[..., :3] / np.float32(255)).tobytes())
        self.assertEqual(alpha[0].tobytes(), (first[..., 3] / np.float32(255)).tobytes())

    def test_ten_bits_and_a_width_off_a_multiple_of_32(self):
        for name in ("prores10_200.mov", "h264_200.mp4"):
            rgb, alpha, n = plateio.decode_video(self.paths[name], 8, 24.0)
            self.assertEqual(rgb.shape, (8, 112, 200, 3), name)
            self.assertTrue(np.isfinite(rgb).all() and rgb.min() > -0.01 and rgb.max() < 1.01, name)



class Sequence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.seqs = {os.path.basename(os.path.dirname(f[0])): f for f in decode_parity.sequences(cls.tmp.name)}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_each_file_in_its_place_and_the_padding(self):
        files = self.seqs["png8"]
        rgb, alpha, n = plateio.decode_frames(files, pad_8n1=True, workers=3)
        self.assertEqual((n, rgb.shape[0]), (5, 9))
        self.assertIsNone(alpha)
        for i, f in enumerate(files):
            self.assertEqual(rgb[i].tobytes(), (np.asarray(Image.open(f).convert("RGB"), np.float32) / np.float32(255)).tobytes())
        self.assertTrue((rgb[5:] == rgb[4]).all())

    def test_half_floats_above_one_with_alpha(self):
        rgb, alpha, n = plateio.decode_frames(self.seqs["exr_half_alpha"])
        self.assertGreater(float(rgb.max()), 1.0)
        self.assertEqual(alpha.shape, rgb.shape[:3])

    def test_a_file_without_the_first_file_alpha_is_refused(self):
        with self.assertRaises(ValueError):
            plateio.decode_frames([self.seqs["png8_alpha"][0], self.seqs["png8"][1]])


if __name__ == "__main__":
    unittest.main()
