"""Upscale's set for an edit that keeps the plate's untouched pixels: the job of the layer's window composes the upscaled
result from the same window of the upscaled plate and the matte, and writes the upscaled matte that composite used."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402
import upscale_plate  # noqa: E402

LAYER = {"under": "output:p/upscale/plate/w001", "under_space": "sRGB", "matte": "output:r/matte", "comp_prefix": "r/upscale/comp/w001/f",
         "matte_prefix": "r/upscaled/matte/matte"}


def by_title(prompt, title):
    (nid, node), = [(k, n) for k, n in prompt.items() if n.get("_meta", {}).get("title") == title]
    return nid, node


def output(prompt, name):
    return next((k, n) for k, n in prompt.items() if n.get("_meta", {}).get("output") == name)


class LayerWindow(unittest.TestCase):
    def setUp(self):
        values = upscale_plate.values("output:r/layer", 1920, 1080, 121, first=21, count=21, color_space="sRGB", window=1)
        self.p = build_workflows.fill("upscale", {**values, **LAYER})

    def test_the_upscaled_result_is_the_plates_window_around_the_matte_and_the_layer_inside(self):
        _, comp = by_title(self.p, "Upscaled result: the plate's window around the matte, the layer inside it")
        bid, _ = by_title(self.p, "The window in the plate's colour space")
        uid, under = by_title(self.p, "The window of the upscaled plate in the layer's colour space")
        lid, load = by_title(self.p, "The window of the upscaled plate")
        self.assertEqual((comp["inputs"]["source"], comp["inputs"]["destination"]), ([bid, 0], [uid, 0]))
        self.assertEqual((under["inputs"]["image"], under["inputs"]["source"], under["inputs"]["destination"]), ([lid, 0], "sRGB", "sRGB"))
        self.assertEqual((load["inputs"]["path"], load["inputs"]["max_frames"]), (LAYER["under"], 21))
        size = self.p[str(comp["inputs"]["width"][0])]
        self.assertEqual((size["class_type"], size["inputs"]["image"]), ("GetImageSize", [bid, 0]))
        _, saved = output(self.p, "comp")
        self.assertEqual((saved["inputs"]["filename_prefix"], saved["inputs"]["format"]), (LAYER["comp_prefix"], "png16"))

    def test_the_matte_is_cut_to_the_window_and_sized_as_composite_frames_sizes_it(self):
        _, comp = by_title(self.p, "Upscaled result: the plate's window around the matte, the layer inside it")
        wid, window = by_title(self.p, "The window of the matte")
        self.assertEqual((window["inputs"]["batch_index"], window["inputs"]["length"]), (21, 21))
        mask = self.p[str(comp["inputs"]["mask"][0])]
        self.assertEqual((mask["class_type"], mask["inputs"]["image"]), ("ImageToMask", [wid, 0]))
        _, big = by_title(self.p, "The matte at the target size (bilinear, as Composite Frames sizes it)")
        self.assertEqual((big["inputs"]["image"], big["inputs"]["upscale_method"], big["inputs"]["crop"]), ([wid, 0], "bilinear", "disabled"))
        self.assertEqual((big["inputs"]["width"], big["inputs"]["height"]), (comp["inputs"]["width"], comp["inputs"]["height"]))
        _, saved = output(self.p, "matte")
        self.assertEqual((saved["inputs"]["format"], saved["inputs"]["filename_prefix"]), ("png16", LAYER["matte_prefix"]))


class OptionalParts(unittest.TestCase):
    def classes(self, values):
        return sorted(n["class_type"] for n in build_workflows.fill("upscale", values).values())

    def test_a_plate_or_a_relight_without_a_matte_runs_the_window_alone(self):
        plain = self.classes(upscale_plate.values("plates/horse.mp4", 1920, 1080, 121))
        self.assertEqual((plain.count("PaintAPlate_LoadPlate"), plain.count("PaintAPlate_SaveFrames")), (1, 1))
        self.assertNotIn("PaintAPlate_CompositeFrames", plain)

    def test_a_relight_with_a_matte_writes_the_upscaled_matte_and_composes_nothing(self):
        v = {**upscale_plate.values("output:r/export", 1920, 1080, 121), "matte": "output:r/matte", "matte_prefix": "r/upscaled/matte/matte"}
        relit = self.classes(v)
        self.assertNotIn("PaintAPlate_CompositeFrames", relit)
        self.assertEqual((relit.count("PaintAPlate_LoadPlate"), relit.count("PaintAPlate_SaveFrames")), (2, 2))


if __name__ == "__main__":
    unittest.main()
