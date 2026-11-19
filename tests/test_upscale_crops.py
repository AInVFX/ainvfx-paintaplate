"""tests/upscale_compare.py crops: the same frame of several results, the same box of each at full size, side by side, for
the sheet of a half against a third; and tests/upscale_plate.py's source at a third."""
import os
import sys
import tempfile
import unittest

from _env import ROOT, require

require("numpy", "PIL", "OpenEXR", "av")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import upscale_compare  # noqa: E402
import upscale_plate  # noqa: E402


class Crops(unittest.TestCase):
    def test_one_frame_of_each_result_the_same_box_side_by_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = []
            for label, level in (("half", 64), ("third", 192)):
                d = os.path.join(tmp, label)
                os.makedirs(d)
                for i in range(3):
                    f = np.full((60, 80, 3), level, np.uint8)
                    f[20:40, 30:50] = 40 * (i + 1)  # frame i + 1 marks the box
                    Image.fromarray(f).save(os.path.join(d, f"f_{i + 1:05d}_.png"))
                results.append((label, d))
            sheet = np.asarray(Image.open(upscale_compare.crops(results, 2, (30, 20, 20, 20), tmp)).convert("RGB"))
        self.assertEqual(sheet.shape, (20, 48, 3))
        self.assertEqual((int(sheet[19, 2, 1]), int(sheet[19, 30, 1])), (80, 80))  # frame 2's box, in each result

    def test_the_source_at_a_third(self):
        self.assertEqual(upscale_plate.source_size(1920, 1080, (3840, 2160)), (0, 0))  # twice the shot: it goes in as it is
        self.assertEqual(upscale_plate.source_size(1920, 1080, (3840, 2160), 3), (1280, 720))
        self.assertEqual(upscale_plate.values("plates/horse.mp4", 1920, 1080, 121, factor=3)["source_width"], 1280)


if __name__ == "__main__":
    unittest.main()
