"""The export's layer: the shot as the composite blends it, at the plate's size, so a compositor rebuilds the result from
the plate, the layer and the matte (result = plate x (1 - matte) + layer x matte)."""
import os
import sys
import tempfile
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

    def test_beside_an_exr_result_the_layer_is_half_float_exr_in_aces2065_1(self):
        _, exr = output(self.p, "layer_exr")
        _, layer = output(self.p, "layer")
        conv = self.p[str(exr["inputs"]["images"][0])]
        self.assertEqual((exr["inputs"]["format"], exr["inputs"]["chromaticities"]), ("exr", "AP0"))
        self.assertEqual((conv["class_type"], conv["inputs"]["image"], conv["inputs"]["destination"]),
                         ("PaintAPlate_ColorSpace", layer["inputs"]["images"], build_workflows.HDR_SPACE))
        (pid, _), = [(k, n) for k, n in of(self.p, "PaintAPlate_LoadPlate") if n["_meta"].get("title") == "Plate"]
        self.assertEqual(exr["inputs"]["frames"], [pid, 4])  # Load Plate's padding stays out

    def test_a_relight_leaves_the_layer_out_and_an_exr_result_keeps_only_its_exr_layer(self):
        titles = lambda p: {n.get("_meta", {}).get("title") for n in p.values()}  # noqa: E731
        outs = lambda p: {n["_meta"]["output"] for n in p.values() if "output" in n.get("_meta", {})}  # noqa: E731
        relit = build_workflows.fill("export", VALUES)
        self.assertFalse({"layer", "layer_exr"} & outs(relit))
        self.assertFalse({"Layer: the shot as the composite blends it", "The layer in ACES2065-1"} & titles(relit))
        edit = build_workflows.fill("export", {**VALUES, "layer_prefix": "r/layer"})
        self.assertEqual({"layer", "layer_exr"} & outs(edit), {"layer"})
        self.assertNotIn("The layer in ACES2065-1", titles(edit))
        hdr = build_workflows.fill("export", {**VALUES, "prefix": "", "exr_prefix": "r/export/f", "layer_exr_prefix": "r/layer/f"})
        self.assertEqual({"export", "exr", "layer", "layer_exr"} & outs(hdr), {"exr", "layer_exr"})

    def test_the_parts_add_up_as_composite_frames_blends_them(self):
        rng = np.random.default_rng(7)
        plate, layer = rng.random((2, 6, 8, 3), np.float32)
        matte = rng.random((6, 8), np.float32)
        expected = matte[..., None] * layer + (1 - matte[..., None]) * plate
        np.testing.assert_array_equal(mathops.composite(plate, layer, matte), expected)


class LayerInTheZip(unittest.TestCase):
    def test_the_zip_puts_the_layer_after_the_result(self):
        import test_routes  # its stand-in for ComfyUI's folder_paths, which routes imports
        routes = test_routes.routes
        with tempfile.TemporaryDirectory() as run:
            for part in ("export", "layer", "matte"):
                os.makedirs(os.path.join(run, part))
                open(os.path.join(run, part, f"{part}_00001_.png"), "w").close()
            names = [arc for _, arc in routes.collect(run, ["matte", "layer", "export"])]
        self.assertEqual(names, ["export/export_00001_.png", "layer/layer_00001_.png", "matte/matte_00001_.png"])

    def test_the_4k_set_is_one_folder_of_the_zip_and_its_windows_stay_out(self):
        import test_routes
        routes = test_routes.routes
        with tempfile.TemporaryDirectory() as run:
            for part in ("4k/export", "4k/plate", "4k/layer", "4k/matte", "upscale/comp/w000", "export"):
                os.makedirs(os.path.join(run, part))
                open(os.path.join(run, part, "f_00001_.png"), "w").close()
            names = [arc for _, arc in routes.collect(run, ["export", "4k"])]
        self.assertEqual(names, ["export/f_00001_.png", "4k/export/f_00001_.png", "4k/layer/f_00001_.png", "4k/matte/f_00001_.png",
                                 "4k/plate/f_00001_.png"])


if __name__ == "__main__":
    unittest.main()
