"""tests/hdr_plate.py: the HDR test plate the laptop makes from horse.mp4, and its measure of the seam."""
import os
import sys
import tempfile
import unittest
import zipfile

from _env import ROOT, require

require("PyOpenColorIO", "numpy", "scipy", "av", "OpenEXR", "PIL")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import av  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import hdr_plate  # noqa: E402
import ocio  # noqa: E402
import plateio  # noqa: E402

LIN709 = "Linear Rec.709 (sRGB)"


def movie(path, n=9, h=48, w=64):
    """A small H.264 movie at 24 fps whose frames hold a white patch, so the lifted plate reaches its peak."""
    with av.open(path, "w") as c:
        s = c.add_stream("libx264", rate=24)
        s.width, s.height, s.pix_fmt = w, h, "yuv420p"
        for i in range(n):
            f = np.zeros((h, w, 3), np.uint8)
            f[..., 0], f[..., 1], f[..., 2] = np.linspace(0, 255, w)[None], 128, (i * 20) % 256
            f[8:24, 8:24] = 255
            c.mux(s.encode(av.VideoFrame.from_ndarray(f, format="rgb24")))
        c.mux(s.encode())


class Lift(unittest.TestCase):
    def test_the_lift_is_the_way_out_and_the_models_see_the_movie(self):
        x = np.random.default_rng(0).uniform(0, 1, (32, 32, 3)).astype(np.float32)
        x[0, 0] = 1.0  # white: the lifted batch's peak is the lift's
        plate = hdr_plate.lift(x, 7.0)
        np.testing.assert_allclose(plate, ocio.out_of_model(x, 7.0), rtol=1e-5, atol=1e-7)
        peak = ocio.batch_peak([plate], ocio.BUILTIN, LIN709)
        self.assertAlmostEqual(peak, 7.0, places=4)
        seen = ocio.convert([plate], ocio.BUILTIN, LIN709, ocio.MODEL, peak)[0]
        np.testing.assert_allclose(seen, x, atol=2e-4)


class MakeAndMeasure(unittest.TestCase):
    def test_make_writes_half_float_frames_with_the_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            movie(os.path.join(tmp, "m.mp4"))
            info = hdr_plate.make(os.path.join(tmp, "m.mp4"), os.path.join(tmp, "hdr"), 7.0, 5)
            frames = plateio.find_sequence(os.path.join(tmp, "hdr"))
            self.assertEqual([os.path.basename(f) for f in frames], [f"hdr.{1001 + i}.exr" for i in range(5)])
            self.assertEqual(float(plateio.exr_rate(frames[0])), 24.0)
            self.assertGreater(info["peak"], 5.0)
            with av.open(os.path.join(tmp, "m.mp4")) as c:
                first = next(c.decode(video=0)).to_ndarray(format="rgb24")
            np.testing.assert_allclose(plateio.read_float(frames[0]), hdr_plate.lift(first / 255.0, 7.0), rtol=2e-3, atol=1e-4)

    def test_seam_reads_the_level_of_the_new_pixels_and_the_untouched_ones(self):
        n, h, w = 4, 64, 80
        rng = np.random.default_rng(1)
        plate = [np.exp(rng.uniform(np.log(0.05), np.log(6.0), (h, w, 1))) * np.ones(3, np.float32) for _ in range(n)]
        matte = np.zeros((h, w), np.float32)
        matte[16:48, 20:60] = 1.0
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "plate"))
            plateio.write_exrs(lambda i: plate[i], [os.path.join(tmp, "plate", f"p.{1001 + i}.exr") for i in range(n)])
            zpath = os.path.join(tmp, "export.zip")
            with zipfile.ZipFile(zpath, "w") as z:
                for i in range(n):
                    r = np.where(matte[..., None] > 0, plate[i] * 2 ** -0.5, plate[i])
                    plateio.write_exrs(lambda _: r, [os.path.join(tmp, "r.exr")])
                    z.write(os.path.join(tmp, "r.exr"), f"export/p.{1001 + i}.exr")
                    Image.fromarray((matte * 255).astype(np.uint8)).save(os.path.join(tmp, "m.png"))
                    z.write(os.path.join(tmp, "m.png"), f"matte/matte_{i:05d}.png")
            got = hdr_plate.seam(os.path.join(tmp, "plate"), zpath, ring=4, every=1)
            self.assertTrue(os.path.exists(os.path.join(tmp, "seam.md")))
        for lo, hi, count, median, *_ in got["rows"]:
            self.assertGreater(count, 0)
            self.assertAlmostEqual(median, -0.5, delta=0.01)
        self.assertEqual(got["untouched"], 0.0)


if __name__ == "__main__":
    unittest.main()
