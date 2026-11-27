"""tests/export3_compare.py: the rows it reads for the folders Finish's graph writes, and the largest difference it measures
between two sets of frames, one pixel changed."""
import os
import tempfile
import unittest

import numpy as np

import export3_compare as compare  # it puts the repository on sys.path
import plateio


class Compare(unittest.TestCase):
    def test_the_row_of_each_folder_finish_writes(self):
        rows = {"hdr/plate": "plate_hdr", "hdr/layer": "layer_hdr", "hdr/comp": "composite_hdr", "upscale/1280x704/out/plate": "plate_upscaled",
                "hdr/upscale/1280x704/out/comp": "composite_hdr_upscaled", "upscale/1280x704/out/matte": "matte_upscaled",
                "upscale/0a1b2c3d/w000": None, "hdr/0a1b2c3d/plate": None, "upscale/1280x704/movie/plate": None}
        self.assertEqual({f: compare.row_of(f) for f in rows}, rows)

    def test_the_largest_difference_of_two_sets_of_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = np.linspace(0, 65535, 4 * 6 * 3).reshape(4, 6, 3).astype(np.uint16)
            moved = frame.copy()
            moved[2, 3, 1] += 655  # 655 of 65535: 0.009995 in floats
            for name, frames in (("page", [frame, frame]), ("graph", [frame, moved])):
                os.makedirs(os.path.join(tmp, name))
                plateio.write_pngs(lambda i, f=frames: f[i], [os.path.join(tmp, name, f"m_{i + 1:05}_.png") for i in range(2)])
            page, graph = (compare.frames([os.path.join(tmp, n, f) for f in sorted(os.listdir(os.path.join(tmp, n)))]) for n in ("page", "graph"))
            diffs = [float(np.max(np.abs(p - g))) for p, g in zip(page, graph)]
        self.assertEqual(diffs[0], 0.0)
        self.assertAlmostEqual(diffs[1], 655 / 65535, places=6)


if __name__ == "__main__":
    unittest.main()
