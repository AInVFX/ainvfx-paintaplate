"""OpenColorIO for the viewer and the workflows (ocio.py): the config, the plate's guessed colour space, conversions into
and out of the model space as core made them, and the viewer's GLSL. Runs without torch or ComfyUI."""
import base64
import os
import sys
import unittest

from _env import ROOT, require

require("PyOpenColorIO", "numpy")
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import ocio  # noqa: E402

LIN709, MODEL = "Linear Rec.709 (sRGB)", "sRGB Encoded Rec.709 (sRGB)"


def core_srgb(frames):
    """Core ComfyUI's linear Rec.709 to sRGB (nodes_images.py, v0.43.0), written again here from its equations."""
    w = np.array([0.2126, 0.7152, 0.0722])
    peak = max(1.0, max(float((f @ w).max()) for f in frames))
    out = []
    for f in frames:
        f = f.astype(np.float64)
        if peak > 1.0001:
            lum = np.maximum(f @ w, 0)[..., None]
            f = f * (1 + lum / peak**2) / (1 + lum)
        lum = np.clip(f @ w, 0, 1)[..., None]
        lo, hi = f.min(-1, keepdims=True), f.max(-1, keepdims=True)
        sat = np.clip(np.minimum((1 - lum) / np.maximum(hi - lum, 1e-30), lum / np.maximum(lum - lo, 1e-30)), 0, 1)
        f = np.clip(np.where((lo >= -1e-5) & (hi <= 1.00001), f, lum + (f - lum) * sat), 0, 1)
        out.append(np.where(f <= 0.0031308, f * 12.92, 1.055 * f ** (1 / 2.4) - 0.055))
    return out


class Config(unittest.TestCase):
    def test_the_built_in_config_and_its_familiar_view(self):
        d = ocio.describe("")
        self.assertEqual((d["model"], d["scene_linear"]), (MODEL, "ACEScg"))
        self.assertEqual((d["display"], d["view"]), ("sRGB - Display", "Un-tone-mapped"))  # SDR plates look as before
        self.assertIn("Input/ARRI", {s["family"] for s in d["spaces"]})  # RV's menu tree comes from the families
        self.assertTrue(any(c["name"] == ocio.BUILTIN for c in d["configs"]))
        for bad in ("/etc/passwd", "ocio://nothing", "$OCIO" if not os.environ.get("OCIO") else "ocio://x"):
            with self.assertRaises(ValueError, msg=bad):
                ocio.config(bad)

    def test_the_plate_colour_space_guessed_from_the_file(self):
        self.assertEqual(ocio.guess("", "linear"), LIN709)
        self.assertEqual(ocio.guess("", "linear ACEScg"), "ACEScg")
        self.assertEqual(ocio.guess("", "sRGB"), MODEL)
        self.assertEqual(ocio.guess("", "HDR PQ"), "Rec.2100-PQ - Display")
        self.assertEqual(ocio.guess("", "", "/shots/a.0001.exr"), "ACES2065-1")  # the config's file rules come last


class Convert(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.sdr = [rng.random((8, 12, 3)).astype(np.float32) * 0.9 for _ in range(3)]
        self.hdr = [f * 1.0 for f in self.sdr]
        self.hdr[1][2, 3] = [6.0, 5.0, 4.0]  # one highlight sets the batch's peak

    def test_into_the_model_space_as_core_made_it(self):
        for frames in (self.sdr, self.hdr):
            got = ocio.convert(frames, "", LIN709, ocio.MODEL)
            for a, b in zip(got, core_srgb(frames)):
                np.testing.assert_allclose(a, b, atol=2e-5)
        self.assertAlmostEqual(float(ocio.decode(ocio.convert(self.hdr, "", LIN709, ocio.MODEL)[1][2, 3]) @ ocio.REC709_LUMA), 1.0, 4)

    def test_out_of_the_model_space_and_through_linear_light(self):
        plate = [f * 3.0 - 0.1 for f in self.sdr]  # ACEScg with values above 1.0 and below 0
        lin = ocio.convert(plate, "", "ACEScg", ocio.LINEAR)
        for a, b in zip(ocio.convert(lin, "", ocio.LINEAR, "ACEScg"), plate):
            np.testing.assert_allclose(a, b, atol=2e-5)
        direct = ocio.convert(self.sdr, "", MODEL, "ACEScg")
        for a, b in zip(ocio.convert(self.sdr, "", ocio.MODEL, "ACEScg"), direct):
            np.testing.assert_array_equal(a, b)

    def test_alpha_stays_and_the_same_space_is_free(self):
        rgba = [np.dstack([f, np.full(f.shape[:2], 0.25, np.float32)]) for f in self.sdr]
        out = ocio.convert(rgba, "", LIN709, "ACEScg")
        self.assertTrue(all(np.all(f[..., 3] == 0.25) for f in out))
        self.assertIs(ocio.convert(self.sdr, "", "ACEScg", "ACEScg")[0], self.sdr[0])


class Shader(unittest.TestCase):
    def test_glsl_es_3_for_webgl2_with_its_tables(self):
        s = ocio.shader("", "ARRI LogC4", "sRGB - Display", "ACES 2.0 - SDR 100 nits (Rec.709)")
        self.assertIn("vec4 ocioIn(", s["in"]["text"])
        self.assertIn("vec4 ocioOut(", s["out"]["text"])
        self.assertFalse(s["identity"])
        for t in s["out"]["tables"]:
            self.assertIn(f"uniform sampler2D {t['sampler']};", s["out"]["text"])
            self.assertEqual(len(base64.b64decode(t["data"])), t["width"] * t["height"] * t["channels"] * 4)
        self.assertTrue(ocio.shader("", MODEL, "sRGB - Display", "Un-tone-mapped")["identity"])  # 8-bit frames drawn as they are
        with self.assertRaises(ValueError):
            ocio.shader("", MODEL, "sRGB - Display", "No such view")


if __name__ == "__main__":
    unittest.main(verbosity=2)
