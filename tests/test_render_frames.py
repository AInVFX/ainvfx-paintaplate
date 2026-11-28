"""The GPU report numbers frames as the plate does: the number of each file for an image sequence, from 1 for a movie."""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpu_matrix  # noqa: E402
from test_render_paint import picture  # noqa: E402


class Frames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="frames_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_sheet_and_its_verdict_carry_a_sequence_s_own_numbers(self):
        plate = os.path.join(self.tmp, "plate")
        with zipfile.ZipFile(os.path.join(self.tmp, "export.zip"), "w") as z:
            for k in range(6):
                picture(os.path.join(plate, f"tos_05_4a.{480 + k:06d}.png"), size=(320, 180))
                z.write(picture(os.path.join(self.tmp, "made", f"{k}.png"), (100, 60, 200, 120), size=(320, 180)), f"export/tos_05_4a.{480 + k:06d}.png")
        strokes = [["erase", "", [[0.4, 0.4], [0.6, 0.6]], 36], ["erase", "", [[0.1, 0.1], [0.2, 0.2]], 36]]
        made = gpu_matrix.sheet({"strokes": strokes}, self.tmp, plate)
        self.assertEqual(made["frames"], [480, 482, 484, 485])
        self.assertEqual(made["verdict"]["text"], "Clean, frame 480: no verdict. 2 Clean edits share the frame.")

    def test_the_paint_matte_s_lines_name_the_plate_s_frames(self):
        lines = gpu_matrix.matte_lines("output/m", [0.05, 0.06, 0.04], [1.0, 1.2, 0.8], 1, [480, 481, 482])
        self.assertEqual(lines[:2], ["- Paint matte (`output/m`): 3 frames; frame 480 covers 5.00% of the frame.",
                                     "- Area against frame 480: 0.80 to 1.20 times. Furthest: frame 481, 1.20 times."])
        self.assertTrue(gpu_matrix.matte_lines("m", [0.05], [1.0], 0, [])[0].endswith("frame 1 covers 5.00% of the frame."))


if __name__ == "__main__":
    unittest.main()
