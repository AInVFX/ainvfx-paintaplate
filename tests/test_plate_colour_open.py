"""The colour space a plate opens in, kind by kind, with OCIO's built-in studio config: what the file says (a movie's
curve tag, an EXR's chromaticities) in that config, else sRGB for a movie or an image and linear Rec.709 for an EXR.
A camera's log movie and a log DPX scan say nothing of their curve: they open as sRGB, and the person chooses the
camera's log space in Open."""
import json
import os
import sys
import tempfile
import unittest
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ocio  # noqa: E402
import plateio  # noqa: E402

av, OpenEXR = plateio.av, plateio.OpenEXR


def opened(path):
    """(the guess from the file, the colour space it names in the built-in config)."""
    spec = plateio.probe_plate(path)
    familiar = plateio.guess_color_space(spec)
    return familiar, ocio.guess(ocio.BUILTIN, familiar, spec["files"][0] if spec.get("files") else path)


@unittest.skipUnless(av is not None and OpenEXR is not None, "PyAV or OpenEXR missing")
class OpenedAs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def movie(self, name, codec, pix_fmt, trc=None):
        path = os.path.join(self.tmp.name, name)
        with av.open(path, "w") as c:
            s = c.add_stream(codec, rate=Fraction(24, 1))
            s.width, s.height, s.pix_fmt = 64, 36, pix_fmt
            if trc:
                s.codec_context.color_trc = trc
            for _ in range(2):
                for p in s.encode(av.VideoFrame.from_ndarray(np.full((36, 64, 3), 100, np.uint8), format="rgb24")):
                    c.mux(p)
            for p in s.encode():
                c.mux(p)
        return path

    def frames(self, name, ext, write):
        folder = os.path.join(self.tmp.name, name)
        os.makedirs(folder)
        for n in (1001, 1002):
            write(os.path.join(folder, f"shot.{n}.{ext}"))
        return folder

    def exr(self, name, gamut=None):
        header = {"chromaticities": plateio.CHROMATICITIES[gamut][0]} if gamut else {}
        return self.frames(name, "exr", lambda p: OpenEXR.File(header, {c: np.full((36, 64), 0.18, np.float16) for c in "RGB"}).write(p))

    def test_movies_and_images_open_as_srgb(self):
        h264 = "libx264" if "libx264" in av.codecs_available else "mpeg4"
        png = self.frames("png16", "png", lambda p: plateio.write_pngs(lambda i: np.full((36, 64, 3), 30000, np.uint16), [p]))
        dpx = self.frames("dpx", "dpx", lambda p: open(p, "wb").write(
            plateio.encode_still(np.full((36, 64, 3), 0.5, np.float32), None, "dpx", "rgb48be", {})))
        for path in (self.movie("h264.mp4", h264, "yuv420p", trc=1), self.movie("prores.mov", "prores_ks", "yuv422p10le"), png, dpx,
                     self.movie("camera_log.mov", "prores_ks", "yuv422p10le")):
            self.assertEqual(opened(path), ("sRGB", "sRGB Encoded Rec.709 (sRGB)"), path)

    @unittest.skipUnless("libx264" in (av.codecs_available if av else ()), "libx264 missing")
    def test_a_movie_tagged_pq_opens_as_pq(self):
        self.assertEqual(opened(self.movie("pq.mp4", "libx264", "yuv420p10le", trc=16)), ("HDR PQ", "Rec.2100-PQ - Display"))

    def test_an_exr_opens_in_the_gamut_its_chromaticities_name(self):
        expected = {"AP0": "ACES2065-1", "AP1": "ACEScg", "Rec.2020": "Linear Rec.2020", "P3-D65": "Linear P3-D65",
                    "Rec.709": "Linear Rec.709 (sRGB)"}
        for gamut, name in expected.items():
            self.assertEqual(opened(self.exr(gamut, gamut))[1], name, gamut)

    def test_an_exr_without_chromaticities_opens_as_linear_rec709(self):
        self.assertEqual(opened(self.exr("plain")), ("linear", "Linear Rec.709 (sRGB)"))

    def test_the_packs_aces2065_1_frames_say_ap0_and_reopen_as_aces2065_1(self):
        folder = os.path.join(self.tmp.name, "hdr")
        os.makedirs(folder)
        plateio.write_exrs(lambda i: np.full((36, 64, 3), 2.0, np.float32), [os.path.join(folder, "f_00001_.exr")], chromaticities="AP0")
        self.assertEqual(opened(folder), ("linear ACES2065-1", "ACES2065-1"))
        root = os.path.dirname(HERE)
        for name in ("hdr", "export"):
            with open(os.path.join(root, "web", "workflows", f"{name}.json")) as f:
                saves = [n for n in json.load(f).values() if n["class_type"] == "PaintAPlate_SaveFrames" and n["inputs"].get("format") == "exr"]
            self.assertTrue(saves, name)
            self.assertEqual({n["inputs"].get("chromaticities") for n in saves}, {"AP0"}, name)

    def test_other_chromaticities_read_as_none_and_float_text_parses(self):
        self.assertIsNone(plateio.gamut_of("(0.7347, 0.2653)"))
        self.assertIsNone(plateio.gamut_of("(0.684, 0.313, 0.221, 0.848, 0.0861, -0.102, 0.3127, 0.329)"))  # ARRI Wide Gamut 3
        self.assertEqual(plateio.gamut_of("V2f(0.7347000241, 0.2653000057) (0.0, 1.0) (9.999999747378752e-05, -0.07699999958) "
                                          "(0.3216800093650818, 0.3376699984073639)"), "linear ACES2065-1")


if __name__ == "__main__":
    unittest.main()
