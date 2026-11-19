"""tests/hdr_plate.py level: each channel's level and the saturation against the plate, the matte left out, what the
result holds where the plate is at its white, and the export's zip read in place of a folder, the upscaled set too."""
import os
import sys
import tempfile
import unittest
import zipfile

from _env import ROOT, require

require("PyOpenColorIO", "numpy", "scipy", "av", "OpenEXR", "PIL")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import hdr_plate  # noqa: E402
import ocio  # noqa: E402
import plateio  # noqa: E402

N = 4
COLOUR = np.array([0.2, 0.0, -0.1], np.float32)  # stops of the result over the plate, by channel, on frames 1 and 2
GAIN = 0.5  # stops of the result over the plate in every channel, on frames 3 and 4


def shot(tmp):
    """A plate (ACEScg, no gamut in its header), the result (ACES2065-1, AP0) with its right half changed, the matte of that
    half, and a zip holding the result, the matte and the result at twice the size."""
    rng = np.random.default_rng(7)
    plate = [rng.uniform(0.05, 0.6, (64, 96, 3)).astype(np.float32) for _ in range(N)]
    result = []
    for k, f in enumerate(plate):
        f[:8, :24] = 1.0  # the plate's white
        r = f * 2.0 ** (COLOUR if k < 2 else np.full(3, GAIN, np.float32))
        r[:8, :24] = 4.0  # two stops over the plate's white
        r[:, 48:] *= 8.0  # the edit
        result.append(ocio.convert([r], ocio.BUILTIN, "ACEScg", "ACES2065-1")[0])
    dirs = {k: os.path.join(tmp, k) for k in ("plate", "result", "big", "matte")}
    for d in dirs.values():
        os.makedirs(d)
    plateio.write_exrs(lambda i: plate[i], [os.path.join(dirs["plate"], f"p_{i:04d}.exr") for i in range(N)], workers=2)
    plateio.write_exrs(lambda i: result[i], [os.path.join(dirs["result"], f"f_{i:04d}.exr") for i in range(N)], workers=2,
                       chromaticities="AP0")
    plateio.write_exrs(lambda i: result[i].repeat(2, 0).repeat(2, 1), [os.path.join(dirs["big"], f"f_{i:04d}.exr") for i in range(N)],
                       workers=2, chromaticities="AP0")
    m = np.zeros((64, 96), np.uint8)
    m[:, 48:] = 255
    for i in range(N):
        Image.fromarray(m, "L").save(os.path.join(dirs["matte"], f"m_{i:04d}.png"))
    zipped = os.path.join(tmp, "export.zip")
    with zipfile.ZipFile(zipped, "w") as z:
        for k, folder in (("result", "export/hdr"), ("big", "export/4k/hdr"), ("matte", "export/matte")):
            for name in sorted(os.listdir(dirs[k])):
                z.write(os.path.join(dirs[k], name), f"{folder}/{name}")
    return dirs, zipped


class Level(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dirs, cls.zipped = shot(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, r):
        for n, *_, ch, sp, sr in r["rows"]:
            want = -COLOUR if n <= 2 else np.full(3, -GAIN)  # level is log2(plate / result)
            np.testing.assert_allclose(ch, want, atol=0.005, err_msg=f"frame {n}")
            if n > 2:
                self.assertAlmostEqual(sr, sp, delta=0.002, msg="a gain changes no saturation")
            else:
                self.assertGreater(abs(sr - sp), 0.005, "a change of colour changes the saturation")
        self.assertAlmostEqual(r["white"]["median"], 2.0, delta=0.01)
        self.assertEqual(r["white"]["frames"], N)

    def test_each_channel_the_saturation_and_the_white_outside_the_matte(self):
        r = hdr_plate.level(self.dirs["plate"], self.dirs["result"], "ACEScg", step=4, matte=self.dirs["matte"])
        self.assertEqual(r["spaces"], ("ACEScg", "ACES2065-1"))  # the result's gamut, read from its header
        self.check(r)
        self.assertIn("## Each channel and the saturation", r["text"])
        self.assertIn("## Where the plate is at its white", r["text"])

    def test_without_the_matte_the_edit_moves_the_level(self):
        r = hdr_plate.level(self.dirs["plate"], self.dirs["result"], "ACEScg", step=4)
        self.assertLess(r["channels"][1], -0.5, "the edited half, three stops up, reaches the median")

    def test_the_export_zip_and_its_upscaled_folder_read_as_the_folders(self):
        for folder in ("export/hdr", "export/4k/hdr"):
            r = hdr_plate.level(self.dirs["plate"], color_space="ACEScg", step=4, export=self.zipped, folder=folder)
            self.assertEqual(r["folder"], folder)
            self.check(r)


if __name__ == "__main__":
    unittest.main()
