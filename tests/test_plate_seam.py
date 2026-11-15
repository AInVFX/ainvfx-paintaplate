"""The seam tool names each frame folder of an export's zip with how far its untouched pixels are from the plate: the
export copies them exactly, while a composite saved elsewhere blends the matte's faint edge, under one 8-bit step."""
import os
import sys
import tempfile
import unittest
import zipfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import hdr_plate  # noqa: E402
import plateio  # noqa: E402


class FrameFolders(unittest.TestCase):
    def test_each_folder_and_its_untouched_difference(self):
        rng = np.random.default_rng(2)
        with tempfile.TemporaryDirectory() as tmp:
            plate = os.path.join(tmp, "plate")
            os.makedirs(plate)
            frames = [rng.uniform(0.0, 6.0, (8, 8, 3)).astype(np.float16).astype(np.float32) for _ in range(3)]
            plateio.write_exrs(lambda i: frames[i], [os.path.join(plate, f"plate.{1001 + i}.exr") for i in range(3)])
            matte = np.zeros((8, 8), np.float32)
            matte[2:6, 2:6] = 1.0
            matte[0, 0] = 0.003  # the matte's faint edge: 0 once saved in 8 bits
            changed = [np.where((matte * 255).astype(np.uint8)[..., None] > 0, 10.0, f) for f in frames]  # where the saved matte shows 0, the plate
            blended = [f * (1 - matte[..., None]) + 10.0 * matte[..., None] for f in frames]
            files = []
            for i in range(3):
                for folder, image in (("export", changed[i]), ("review", blended[i])):
                    path = os.path.join(tmp, f"{folder}_{i}.exr")
                    plateio.write_exrs(lambda _, x=image: x, [path])
                    files.append((path, f"{folder}/f_{i + 1:05d}_.exr"))
                path = os.path.join(tmp, f"matte_{i}.png")
                Image.fromarray(np.repeat((matte[..., None] * 255).astype(np.uint8), 3, -1)).save(path)
                files.append((path, f"matte/matte_{i + 1:05d}_.png"))
            export = os.path.join(tmp, "export.zip")
            with zipfile.ZipFile(export, "w") as z:
                for path, name in files:
                    z.write(path, name)
            rows = {f: (n, d) for f, n, d in hdr_plate.groups(plate, export, every=1)["rows"]}
        self.assertEqual(rows["export"], (3, 0.0))
        self.assertEqual(rows["matte"], (3, None))  # PNG frames only: no result to compare
        self.assertGreater(rows["review"][1], 0.02)  # 0.003 of a value 10 away from the plate


if __name__ == "__main__":
    unittest.main()
