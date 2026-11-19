"""tests/gpu_matrix.py image_rgb: an EXR frame on the GPU report's sheet in display colours, from the colour space its
header names, through the built-in OCIO config."""
import os
import sys
import tempfile
import unittest

from _env import ROOT, require

require("PyOpenColorIO", "numpy", "OpenEXR", "PIL")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import numpy as np  # noqa: E402
import gpu_matrix  # noqa: E402
import ocio  # noqa: E402
import plateio  # noqa: E402


class SheetColours(unittest.TestCase):
    def test_an_aces2065_frame_shows_its_rec709_colours_in_srgb(self):
        lin = np.zeros((8, 8, 3), np.float32)
        lin[:, :4], lin[:, 4:] = (0.50, 0.10, 0.05), 0.18  # linear Rec.709: an orange and a mid-grey
        ap0 = ocio.convert([lin], ocio.BUILTIN, ocio.guess(ocio.BUILTIN, "linear"), "ACES2065-1")[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f_0001.exr")
            plateio.write_exrs(lambda i: ap0, [path], workers=1, chromaticities="AP0")
            shown = gpu_matrix.image_rgb(path).astype(int)
            plain = (np.clip(plateio.read_float(path)[..., :3], 0, 1) ** (1 / 2.2) * 255).astype(int)
        want = np.round(np.clip(ocio.encode(lin), 0, 1) * 255).astype(int)
        self.assertLessEqual(np.abs(shown - want).max(), 1)
        self.assertGreater(np.abs(plain - want).max(), 8)  # ACES2065-1 values under a plain 2.2 gamma show other colours

    def test_values_above_white_show_at_white(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f_0001.exr")
            plateio.write_exrs(lambda i: np.full((4, 4, 3), 6.0, np.float32), [path], workers=1)
            self.assertEqual(gpu_matrix.image_rgb(path).min(), 255)


if __name__ == "__main__":
    unittest.main()
