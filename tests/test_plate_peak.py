"""PL6: the plate's peak read once. Color Space (OCIO)'s second output is the peak its tone mapping took on the way into
the model space (ocio.convert_with_peak). The composite's return and Relight Transfer take it as a number; until 1.11.14
each read the whole plate again. It is the float they read, so their pictures are the same bytes."""
import json
import os
import sys
import unittest

from _env import ROOT, require

require("numpy", "PyOpenColorIO")
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import ocio  # noqa: E402

SPACES = ("ACEScg", "Linear Rec.709 (sRGB)", "sRGB Encoded Rec.709 (sRGB)", "ACES2065-1")


def relight_read(plate, src):
    """What Relight Transfer read until 1.11.14 (ocio.linear_peak, gone in PL6): the peak of the plate in @linear."""
    lin = ocio.convert(plate, ocio.BUILTIN, src, ocio.LINEAR)
    return max(1.0, max(float(np.max(f[..., :3] @ ocio.REC709_LUMA, initial=0.0)) for f in lin))


class Peak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(7)
        cls.plates = {}
        for src in SPACES:
            hi = 1.0 if "Encoded" in src else 7.4  # values up to 7.4 in the scene-linear spaces, as Tears of Steel's
            frames = [(rng.random((36, 64, 3)) ** 3 * hi).astype(np.float32) for _ in range(5)]
            frames[2][5, 7] = [hi, 0.9 * hi, 0.8 * hi]
            cls.plates[src] = frames
        cls.shot = [rng.random((36, 64, 3)).astype(np.float32) for _ in range(3)]  # as the model makes it, in @model

    def test_the_peak_taken_on_the_way_in_is_the_float_every_reader_read(self):
        for src, plate in self.plates.items():
            with self.subTest(src):
                model, peak = ocio.convert_with_peak(plate, ocio.BUILTIN, src, ocio.MODEL)
                same = ocio.convert(plate, ocio.BUILTIN, src, ocio.MODEL)
                self.assertTrue(all(a.tobytes() == b.tobytes() for a, b in zip(model, same)))
                self.assertEqual(peak, ocio.batch_peak(plate, ocio.BUILTIN, src))  # the shot's return's read
                self.assertEqual(peak, relight_read(plate, src))  # Relight Transfer's read
                if "Encoded" not in src:
                    self.assertGreater(peak, ocio.TONE_ABOVE)  # so the next test undoes a tone mapping

    def test_the_return_and_relight_transfer_make_the_same_bytes(self):
        for src, plate in self.plates.items():
            with self.subTest(src):
                _, peak = ocio.convert_with_peak(plate, ocio.BUILTIN, src, ocio.MODEL)
                given = ocio.convert(self.shot, ocio.BUILTIN, ocio.MODEL, src, peak)
                read = ocio.convert(self.shot, ocio.BUILTIN, ocio.MODEL, src, ocio.batch_peak(plate, ocio.BUILTIN, src))
                self.assertTrue(all(a.tobytes() == b.tobytes() for a, b in zip(given, read)))
                lin = relight_read(plate, src)
                for f in self.shot:
                    self.assertEqual(ocio.out_of_model(f, peak).tobytes(), ocio.out_of_model(f, lin).tobytes())

    def test_the_peak_where_there_is_no_tone_mapping(self):
        plate, cfg = self.plates["ACEScg"], ocio.BUILTIN
        self.assertEqual(ocio.convert_with_peak(plate, cfg, "ACEScg", ocio.LINEAR)[1], 1.0)
        self.assertEqual(ocio.convert_with_peak(plate, cfg, "ACEScg", "ACEScg")[1], 1.0)
        self.assertEqual(ocio.convert_with_peak(self.shot, cfg, ocio.MODEL, "ACEScg")[1], 1.0)
        self.assertEqual(ocio.convert_with_peak(self.shot, cfg, ocio.MODEL, "ACEScg", 6.0)[1], 6.0)


class Workflows(unittest.TestCase):
    def test_review_and_export_read_the_plate_peak_once(self):
        for name in ("review", "export"):
            with self.subTest(name):
                with open(os.path.join(ROOT, "web", "workflows", f"{name}.json")) as f:
                    p = json.load(f)
                plate = [k for k, n in p.items() if n.get("_meta", {}).get("title") == "Plate in the model space"]
                self.assertEqual(len(plate), 1)
                takers = sorted((n["class_type"], k) for n in p.values() for k, v in n["inputs"].items() if v == [plate[0], 1])
                self.assertEqual(takers, [("PaintAPlate_ColorSpace", "peak"), ("PaintAPlate_RelightTransfer", "peak")])
                self.assertEqual([n["_meta"].get("title") for n in p.values() if "peak_of" in n["inputs"]], [])


if __name__ == "__main__":
    unittest.main()
