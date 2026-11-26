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

    def test_a_shot_under_the_output_folder_or_the_input_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "input", "plates"))
            open(os.path.join(tmp, "input", "plates", "horse.mp4"), "w").close()
            self.assertEqual(upscale_plate.shot_path(tmp, "output:u3/hdr"), os.path.join(tmp, "output", "u3", "hdr"))
            self.assertEqual(upscale_plate.shot_path(tmp, "plates/horse.mp4"), os.path.join(tmp, "input", "plates", "horse.mp4"))
            self.assertEqual(upscale_plate.shot_path(tmp, "elsewhere/horse.mp4"), os.path.join(tmp, "input", "plates", "horse.mp4"))

    def test_the_window_is_sized_in_floats(self):
        self.assertEqual(upscale_plate.resize_method(1920, 1080, (3840, 2160)), "bicubic")  # up, as the page sizes it
        self.assertEqual(upscale_plate.resize_method(3840, 2160, (2560, 1440)), "area")  # down, with no aliasing
        self.assertEqual(upscale_plate.values("plates/horse.mp4", 1920, 1080, 121)["resize_method"], "bicubic")


if __name__ == "__main__":
    unittest.main()
