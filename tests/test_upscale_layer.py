"""The export's layer: the shot as the composite blends it, at the plate's size, so a compositor rebuilds the result from
the plate, the layer and the matte (result = plate x (1 - matte) + layer x matte)."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402
import mathops  # noqa: E402

VALUES = {"path": "plates/horse.mp4", "shot": "output:s/full", "matte_a": "output:m/a", "matte_b": "output:m/b",
          "prefix": "r/export", "matte_prefix": "r/matte/matte", "color_space": "sRGB"}


def of(prompt, cls):
    return [(k, n) for k, n in prompt.items() if n["class_type"] == cls]


def output(prompt, name):
    return next((k, n) for k, n in prompt.items() if n.get("_meta", {}).get("output") == name)



class ExportLayer(unittest.TestCase):
    def setUp(self):
        self.p, self.slots, self.outs = build_workflows.load("export")

    def test_the_layer_is_the_shot_the_composite_blends_sized_by_the_same_filter(self):
        (fid, _), = of(self.p, "PaintAPlate_FitToPlate")
        (_, comp), = of(self.p, "PaintAPlate_CompositeFrames")
        lid, layer = output(self.p, "layer")
        scale = self.p[str(layer["inputs"]["images"][0])]
        self.assertEqual(comp["inputs"]["source"], [fid, 0])
        self.assertEqual((scale["class_type"], scale["inputs"]["image"], scale["inputs"]["upscale_method"], scale["inputs"]["crop"]),
                         ("ImageScale", [fid, 0], "bilinear", "disabled"))
        size = self.p[str(scale["inputs"]["width"][0])]
        (pid, _), = [(k, n) for k, n in of(self.p, "PaintAPlate_LoadPlate") if n["_meta"].get("title") == "Plate"]
        self.assertEqual((size["class_type"], size["inputs"]["image"]), ("GetImageSize", [pid, 0]))
        self.assertEqual((layer["class_type"], layer["inputs"]["plate"], layer["inputs"]["keep_untouched"]),
                         ("PaintAPlate_SavePlate", [pid, 2], False))
        self.assertEqual(self.slots["layer_prefix"], [[lid, "filename_prefix"]])

    def test_a_relight_leaves_the_layer_out(self):
        titles = lambda p: {n.get("_meta", {}).get("title") for n in p.values()}  # noqa: E731
        outs = lambda p: {n["_meta"]["output"] for n in p.values() if "output" in n.get("_meta", {})}  # noqa: E731
        relit = build_workflows.fill("export", VALUES)
        self.assertNotIn("layer", outs(relit))
        self.assertNotIn("Layer: the shot as the composite blends it", titles(relit))
        self.assertIn("layer", outs(build_workflows.fill("export", {**VALUES, "layer_prefix": "r/layer"})))

    def test_the_parts_add_up_as_composite_frames_blends_them(self):
        rng = np.random.default_rng(7)
        plate, layer = rng.random((2, 6, 8, 3), np.float32)
        matte = rng.random((6, 8), np.float32)
        expected = matte[..., None] * layer + (1 - matte[..., None]) * plate
        np.testing.assert_array_equal(mathops.composite(plate, layer, matte), expected)


if __name__ == "__main__":
    unittest.main()
