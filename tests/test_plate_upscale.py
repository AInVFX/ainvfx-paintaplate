"""Upscale to 4K: the workflow's window and colour round trip, its model files, and the window tool's slots and size."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402
import get_models  # noqa: E402
import upscale_plate  # noqa: E402


def workflow():
    with open(os.path.join(ROOT, "web", "workflows", "upscale.json")) as f:
        return json.load(f)


def of(prompt, cls):
    return [(k, n) for k, n in prompt.items() if n["class_type"] == cls]


def slots(prompt):
    return {s for n in prompt.values() for s in n.get("_meta", {}).get("slots", {}).values()}


class UpscaleWorkflow(unittest.TestCase):
    def setUp(self):
        self.p = workflow()

    def test_the_window_is_cut_from_the_whole_shot_and_converted_with_its_peak(self):
        (lid, _), = of(self.p, "PaintAPlate_LoadPlate")
        (cid, cut), = of(self.p, "ImageFromBatch")
        self.assertEqual(cut["inputs"]["image"], [lid, 0])
        self.assertEqual(cut["_meta"]["slots"], {"batch_index": "first", "length": "count"})
        (iid, into), (_, back) = of(self.p, "PaintAPlate_ColorSpace")
        self.assertEqual((into["inputs"]["image"], into["inputs"]["peak_of"], into["inputs"]["destination"]), ([cid, 0], [lid, 0], "@model"))
        self.assertEqual((back["inputs"]["source"], back["inputs"]["peak"], back["_meta"]["slots"]["destination"]), ("@model", [iid, 1], "color_space"))

    def test_seedvr2_samples_chunks_of_21_frames_in_one_step(self):
        (_, chunk), = of(self.p, "SeedVR2TemporalChunk")
        self.assertEqual(chunk["inputs"]["chunking_mode.frames_per_chunk"], build_workflows.UPSCALE_CHUNK)
        self.assertEqual(build_workflows.UPSCALE_CHUNK, 21)
        (_, ks), = of(self.p, "KSampler")
        self.assertEqual((ks["inputs"]["steps"], ks["inputs"]["denoise"], ks["_meta"]["slots"]["seed"]), (1, 1.0, "seed"))
        (_, post), = of(self.p, "SeedVR2PostProcessing")
        self.assertEqual((post["inputs"]["color_correction_method"], post["_meta"]["slots"]["color_correction_method"]), ("lab", "color_fix"))

    def test_save_frames_writes_the_window_back_in_the_plates_colour_space(self):
        (_, save), = of(self.p, "PaintAPlate_SaveFrames")
        (_, _), (bid, _) = of(self.p, "PaintAPlate_ColorSpace")
        self.assertEqual((save["inputs"]["images"], save["_meta"]["output"]), ([bid, 0], "frames"))
        self.assertEqual({save["_meta"]["slots"][k] for k in ("filename_prefix", "format")}, {"prefix", "format"})

    def test_its_model_files_are_optional_downloads_at_a_pinned_revision(self):
        loaded = {n["inputs"].get(k) for n in self.p.values() for k in ("unet_name", "vae_name")} - {None}
        self.assertEqual(loaded, set(get_models.UPSCALE))
        self.assertTrue(set(get_models.UPSCALE) <= set(get_models.OPTIONAL))
        repos = {os.path.basename(p): r for r, p, _ in get_models.MODELS}
        for name in get_models.UPSCALE:
            self.assertIn(repos[name], get_models.REVISIONS)
            self.assertIn(name, get_models.SIZES)


class WindowTool(unittest.TestCase):
    def test_the_target_is_3840_on_the_long_side_in_even_numbers(self):
        self.assertEqual(upscale_plate.target_size(1920, 1080), (3840, 2160))
        self.assertEqual(upscale_plate.target_size(1080, 1920), (2160, 3840))
        self.assertEqual(upscale_plate.target_size(2048, 858), (3840, 1608))
        self.assertEqual(upscale_plate.target_size(3840, 1600), (3840, 1600))
        self.assertEqual(upscale_plate.target_size(4096, 2160), (4096, 2160))

    def test_a_shot_larger_than_half_the_target_comes_down_to_it_first(self):
        self.assertEqual(upscale_plate.source_size(1920, 1080, (3840, 2160)), (0, 0))
        self.assertEqual(upscale_plate.source_size(1280, 720, (3840, 2160)), (0, 0))
        self.assertEqual(upscale_plate.source_size(3840, 2160, (3840, 2160)), (1920, 1080))
        self.assertEqual(upscale_plate.source_size(2560, 1440, (3840, 2160)), (1920, 1080))
        self.assertEqual(upscale_plate.source_size(4096, 1716, (4096, 1716)), (2048, 858))
        p = workflow()
        (sid, source), (_, resized) = of(p, "ImageScale")
        self.assertEqual(source["_meta"]["slots"], {"width": "source_width", "height": "source_height"})
        self.assertEqual((source["inputs"]["width"], source["inputs"]["height"], resized["inputs"]["image"]), (0, 0, [sid, 0]))

    def test_its_values_fill_every_slot_but_the_config(self):
        v = upscale_plate.values("plates/horse.mp4", 1920, 1080, 121, first=84, count=42)
        self.assertEqual(set(v) | {"config"}, slots(workflow()))
        self.assertEqual((v["first"], v["count"], v["width"], v["height"]), (84, 37, 3840, 2160))


if __name__ == "__main__":
    unittest.main()
