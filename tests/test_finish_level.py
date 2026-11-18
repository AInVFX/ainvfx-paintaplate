"""tests/hdr_plate.py level: the HDR frames' level against the plate, frame by frame, in ACEScg."""
import os
import sys
import tempfile
import unittest

from _env import ROOT, require

require("PyOpenColorIO", "numpy", "scipy", "av", "OpenEXR")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import numpy as np  # noqa: E402
import hdr_plate  # noqa: E402
import ocio  # noqa: E402
import plateio  # noqa: E402


class Level(unittest.TestCase):
    def test_each_frame_reads_the_gain_put_in_and_the_frames_off_the_median_are_named(self):
        rng = np.random.default_rng(5)
        plate = [rng.uniform(0.05, 0.6, (64, 96, 3)).astype(np.float32) for _ in range(5)]  # scene-linear, ACEScg
        gains = [0.3, 0.25, 0.0, 0.0, 0.0]  # stops of the HDR frame over the plate
        with tempfile.TemporaryDirectory() as tmp:
            pdir, hdir = os.path.join(tmp, "plate"), os.path.join(tmp, "hdr")
            os.makedirs(pdir), os.makedirs(hdir)
            plateio.write_exrs(lambda i: plate[i], [os.path.join(pdir, f"p_{i:04d}.exr") for i in range(5)], workers=2)
            hdr = [ocio.convert([f * 2.0 ** g], ocio.BUILTIN, "ACEScg", "ACES2065-1")[0] for f, g in zip(plate, gains)]
            plateio.write_exrs(lambda i: hdr[i], [os.path.join(hdir, f"h_{i:04d}.exr") for i in range(5)], workers=2)
            r = hdr_plate.level(pdir, hdir, "ACEScg", step=4)
        for (n, lv, *_), g in zip(r["rows"], gains):
            self.assertAlmostEqual(lv, -g, delta=0.003)
        self.assertAlmostEqual(r["median"], 0.0, delta=0.003)
        self.assertEqual([n for n, _ in r["off"]], [1, 2])
        rows = r["rows"]  # the HDR frame's change of level is the plate's change plus the change of gain
        for k in (1, 2):
            change = np.log2(rows[k][3] / rows[k - 1][3]) - np.log2(rows[k][2] / rows[k - 1][2])
            self.assertAlmostEqual(change, gains[k] - gains[k - 1], delta=0.005)
        self.assertIn("Frames more than 0.02 stops from the shot's median: 1 (-0.300), 2 (-0.250).", r["text"])


if __name__ == "__main__":
    unittest.main()
