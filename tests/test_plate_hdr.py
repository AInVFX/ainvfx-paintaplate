"""SDR to HDR's frames into ACEScg scene-linear: the config's own ACEScct conversion against the ACES curve and against
Lightricks' LTXVHDRDecodePostprocess, one array for a batch, Keep Black's floor at 0, and the hdr workflow's chain."""
import importlib.util
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
import build_workflows  # noqa: E402
import mathops  # noqa: E402
import ocio  # noqa: E402

# ACEScct, Academy S-2016-001: log2 above the break, a straight line below it
BREAK, SLOPE, OFFSET = 0.155251141552511, 10.5402377416545, 0.0729055341958355
HALF = 2.0 ** -12  # half a step of a half float, the precision of the EXR frames
LTX = os.environ.get("LTXVIDEO_DIR", "")


def aces_curve(codes):
    codes = np.clip(codes.astype(np.float64), 0.0, 1.0)
    return np.where(codes > BREAK, 2.0 ** (codes * 17.52 - 9.72), (codes - OFFSET) / SLOPE)


def codes(frames=3, h=24, w=32):
    """Every 12-bit ACEScct code once, then random codes: `frames` frames of h x w x 3."""
    ramp = np.linspace(0.0, 1.0, 4096, dtype=np.float32)
    rest = np.random.default_rng(7).random(frames * h * w * 3 - ramp.size, dtype=np.float32)
    return np.concatenate([ramp, rest]).reshape(frames, h, w, 3)


def to_linear(x):
    """The hdr workflow's chain on frames of codes: Color Space (OCIO) from ACEScct to ACEScg, then Keep Black where the
    SDR shot is bright everywhere, which leaves only its floor at 0."""
    bright = np.ones(x.shape[1:], np.float32)
    return np.stack([mathops.keep_black(f, bright) for f in ocio.convert(list(x), ocio.BUILTIN, "ACEScct", "ACEScg")])


def largest(ours, ref):
    """The largest error, and whether every value is within half a half-float step of `ref`."""
    err = np.abs(np.asarray(ours, np.float64) - ref)
    return float(err.max()), bool((err <= HALF * np.abs(ref) + 1e-7).all())


class AcesCctTest(unittest.TestCase):
    def test_the_config_decodes_acescct_with_the_aces_curve(self):
        x = codes()
        worst, within = largest(ocio.convert(list(x), ocio.BUILTIN, "ACEScct", "ACEScg"), aces_curve(x))
        self.assertTrue(within, f"largest error {worst:.3g}")

    def test_a_conversion_writes_one_array_with_each_frame_as_converted_alone(self):
        x = codes()
        out = ocio.convert(list(x), ocio.BUILTIN, "ACEScct", "ACEScg")
        self.assertIsInstance(out, np.ndarray)
        self.assertEqual(x.shape, out.shape)
        for i, frame in enumerate(x):
            np.testing.assert_array_equal(ocio.convert([frame], ocio.BUILTIN, "ACEScct", "ACEScg")[0], out[i])

    def test_keep_black_floors_at_zero_and_keeps_highlights(self):
        hdr = np.array([[[-0.004, 0.2, 7.5]]], np.float32)
        np.testing.assert_array_equal(np.array([[[0.0, 0.2, 7.5]]], np.float32), mathops.keep_black(hdr, np.ones_like(hdr)))

    def test_the_chain_gives_no_value_below_zero(self):
        self.assertGreaterEqual(float(to_linear(codes()).min()), 0.0)


@unittest.skipUnless(LTX and importlib.util.find_spec("torch") and importlib.util.find_spec("colour"),
                     "needs LTXVIDEO_DIR, torch and colour-science: run it with ComfyUI's Python")
class LightricksTest(unittest.TestCase):
    def test_the_same_values_as_lightricks_postprocess(self):
        import torch
        with open(os.path.join(LTX, "hdr_nodes.py")) as f:
            source = f.read()
        # the steps of LTXVHDRDecodePostprocess that give its linear output: the ACEScct curve, then a clamp to [0, 1e4]
        self.assertIn("return decompress_acescct(decoded_01.float())", source)
        self.assertIn("hdr = torch.clamp(hdr, min=0.0, max=1e4)", source)
        spec = importlib.util.spec_from_file_location("ltx_hdr_color", os.path.join(LTX, "hdr_color.py"))
        lightricks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lightricks)
        x = codes()
        theirs = torch.clamp(lightricks.decompress_acescct(torch.from_numpy(x)), 0.0, 1e4).numpy().astype(np.float64)
        worst, within = largest(to_linear(x), theirs)
        self.assertTrue(within, f"largest error {worst:.3g}")


class HdrWorkflowTest(unittest.TestCase):
    def test_hdr_decodes_with_color_space_and_keep_black_reads_the_shot_as_loaded(self):
        prompt, _, _ = build_workflows.load("hdr")
        self.assertNotIn("LTXVHDRDecodePostprocess", {n["class_type"] for n in prompt.values()})
        keep = next(n for n in prompt.values() if n["class_type"] == "PaintAPlate_KeepBlack")
        decode = prompt[str(keep["inputs"]["hdr"][0])]
        self.assertEqual(("PaintAPlate_ColorSpace", "ACEScct", "ACEScg"),
                         (decode["class_type"], decode["inputs"]["source"], decode["inputs"]["destination"]))
        self.assertEqual("VAEDecodeTiled", prompt[str(decode["inputs"]["image"][0])]["class_type"])
        self.assertEqual("PaintAPlate_LoadPlate", prompt[str(keep["inputs"]["sdr"][0])]["class_type"])
        self.assertEqual("@model", keep["inputs"]["source"])

    def test_hdr_computes_its_vae_in_float32_through_core(self):
        prompt, slots, _ = build_workflows.load("hdr")
        (dtype,) = [k for k, n in prompt.items() if n["class_type"] == "VAEComputeDtype"]
        self.assertEqual("fp32", prompt[dtype]["inputs"]["dtype"])
        loader = prompt[str(prompt[dtype]["inputs"]["vae"][0])]
        self.assertEqual("VAELoader", loader["class_type"])
        self.assertIn([str(prompt[dtype]["inputs"]["vae"][0]), "vae_name"], slots["video_vae"])
        for cls in ("LTXAddVideoICLoRAGuide", "VAEDecodeTiled"):  # the guide's encode and the shot's decode
            node = next(n for n in prompt.values() if n["class_type"] == cls)
            self.assertEqual(dtype, str(node["inputs"]["vae"][0]), cls)
        for name in ("hdr", "fluid", "shot", "clean", "cleanup"):
            self.assertNotIn("PaintAPlate_VAEFloat32", {n["class_type"] for n in build_workflows.load(name)[0].values()}, name)


if __name__ == "__main__":
    unittest.main()
