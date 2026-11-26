"""« Composite, HDR »: the hdr_comp workflow composes the HDR set from its elements, as Upscale composes its set. The plate
through SDR to HDR around the export's matte, the layer through SDR to HDR inside it, through Composite Frames at the plate's
size; the set's composite, its copy of the plate and its matte are written beside the layer, so they rebuild the composite."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402

SET = {"plate": "output:paintaplate/p/hdr/k/f", "layer": "output:r/hdr/layer", "matte": "output:r/matte", "max_frames": 33,
       "comp_prefix": "r/hdr/comp/f", "plate_prefix": "r/hdr/plate/f", "matte_prefix": "r/hdr/matte/matte", "movie_fps": 25.0,
       "video_prefix": "r/hdr/movie/comp"}


def by_title(prompt, title):
    (nid, node), = [(k, n) for k, n in prompt.items() if n.get("_meta", {}).get("title") == title]
    return nid, node


def output(prompt, name):
    return next(n for n in prompt.values() if n.get("_meta", {}).get("output") == name)


class HdrComp(unittest.TestCase):
    def setUp(self):
        self.p = build_workflows.fill("hdr_comp", SET)

    def test_the_composite_is_the_plate_around_the_matte_and_the_layer_inside_at_the_plates_size(self):
        _, comp = by_title(self.p, "Composite, HDR: the plate around the matte, the layer inside it")
        pid, plate = by_title(self.p, "Plate, HDR")
        lid, layer = by_title(self.p, "Layer, HDR")
        mid, matte = by_title(self.p, "Matte")
        self.assertEqual((comp["inputs"]["destination"], comp["inputs"]["source"]), ([pid, 0], [lid, 0]))
        mask = self.p[str(comp["inputs"]["mask"][0])]
        self.assertEqual((mask["class_type"], mask["inputs"]["image"], mask["inputs"]["channel"]), ("ImageToMask", [mid, 0], "red"))
        size = self.p[str(comp["inputs"]["width"][0])]
        self.assertEqual((size["class_type"], size["inputs"]["image"], comp["inputs"]["height"][0]), ("GetImageSize", [pid, 0], comp["inputs"]["width"][0]))
        for load, key in ((plate, "plate"), (layer, "layer"), (matte, "matte")):
            self.assertEqual((load["inputs"]["path"], load["inputs"]["max_frames"], load["inputs"]["pad_8n1"]), (SET[key], 33, False))

    def test_the_set_is_written_beside_the_layer_the_composite_and_plate_as_exr_the_matte_as_16_bit_png(self):
        cid, _ = by_title(self.p, "Composite, HDR: the plate around the matte, the layer inside it")
        pid, _ = by_title(self.p, "Plate, HDR")
        mid, _ = by_title(self.p, "Matte")
        for name, image, fmt, prefix in (("comp", cid, "exr", "comp_prefix"), ("plate", pid, "exr", "plate_prefix"), ("matte", mid, "png16", "matte_prefix")):
            saved = output(self.p, name)
            self.assertEqual((saved["inputs"]["images"], saved["inputs"]["format"], saved["inputs"]["filename_prefix"], saved["inputs"]["fps"],
                              saved["inputs"]["frames"]), ([image, 0], fmt, SET[prefix], 25.0, [pid, 4]), name)
            self.assertEqual(saved["inputs"].get("chromaticities"), "AP0" if fmt == "exr" else None, name)

    def test_the_viewer_movie_shows_the_composite_in_log_values(self):
        cid, _ = by_title(self.p, "Composite, HDR: the plate around the matte, the layer inside it")
        movie = output(self.p, "movie")
        values = self.p[str(movie["inputs"]["images"][0])]
        self.assertEqual((values["inputs"]["image"], values["inputs"]["source"], values["inputs"]["destination"]),
                         ([cid, 0], build_workflows.HDR_SPACE, "ACEScct"))
        self.assertEqual(movie["inputs"]["filename_prefix"], SET["video_prefix"])


if __name__ == "__main__":
    unittest.main()
