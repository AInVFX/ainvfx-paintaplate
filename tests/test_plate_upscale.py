"""Upscale to 4K: the workflow's window and colour round trip, its model files, and the window tool's slots and size."""
import json
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
import get_models  # noqa: E402
import plateio  # noqa: E402
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
        self.assertEqual(cut["inputs"]["length"], build_workflows.UPSCALE_CHUNK)
        (iid, into), (_, back) = of(self.p, "PaintAPlate_ColorSpace")
        self.assertEqual((into["inputs"]["image"], into["inputs"]["peak_of"], into["inputs"]["destination"]), ([cid, 0], [lid, 0], "@model"))
        self.assertEqual((back["inputs"]["source"], back["inputs"]["peak"], back["_meta"]["slots"]["destination"]), ("@model", [iid, 1], "color_space"))

    def test_seedvr2_samples_chunks_of_21_frames_in_one_step(self):
        (_, chunk), = of(self.p, "SeedVR2TemporalChunk")
        self.assertEqual(chunk["inputs"]["chunking_mode.frames_per_chunk"], build_workflows.UPSCALE_CHUNK)
        self.assertEqual((chunk["inputs"]["temporal_overlap"], build_workflows.UPSCALE_OVERLAP), (1, 4))  # one latent frame
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


class ExportJob(unittest.TestCase):
    def test_join_windows_feeds_save_plate_in_the_results_format_with_no_source_pixel(self):
        with open(os.path.join(ROOT, "web", "workflows", "upscale_export.json")) as f:
            p = json.load(f)
        (sid, shot), = of(p, "PaintAPlate_LoadPlate")
        (jid, join), = of(p, "PaintAPlate_JoinWindows")
        (_, save), = of(p, "PaintAPlate_SavePlate")
        self.assertEqual((shot["_meta"]["slots"]["path"], join["_meta"]["slots"]), ("shot", {"folder": "frames", "overlap": "overlap"}))
        self.assertEqual(join["inputs"]["overlap"], build_workflows.UPSCALE_OVERLAP)
        self.assertEqual((save["inputs"]["images"], save["inputs"]["plate"], save["inputs"]["keep_untouched"]), ([jid, 0], [sid, 2], False))
        self.assertEqual(save["_meta"]["output"], "export")
        self.assertEqual(set(upscale_plate.export_values("plates/horse.mp4", 121)), slots(p))

    def test_windows_share_four_frames_and_save_one_folder_each(self):
        self.assertEqual(upscale_plate.windows(121, every=True), [(0, 21), (17, 21), (34, 21), (51, 21), (68, 21), (85, 21), (102, 19)])
        self.assertEqual(upscale_plate.windows(121, 0, 121, every=True), [(0, 121)])
        self.assertEqual(upscale_plate.windows(121, 84, 42), [(84, 37)])
        self.assertEqual(upscale_plate.WINDOW, build_workflows.UPSCALE_CHUNK)
        self.assertEqual(upscale_plate.values("plates/horse.mp4", 1920, 1080, 121, window=3)["prefix"], "upscale/upscale/w003/f")
        self.assertEqual(upscale_plate.export_values("plates/horse.mp4", 121)["frames"], "output:upscale/upscale")
        with open(os.path.join(ROOT, "folders.py")) as f:
            self.assertIn(f'\nOUTPUT = "{upscale_plate.OUTPUT}"', f.read())

    def test_a_window_is_sized_to_the_machines_ram_and_gpu(self):
        hd, uhd = (1920, 1080), (3840, 2160)
        self.assertEqual(upscale_plate.window_frames(52.0, 15.6, uhd, hd, 121), 33)  # a 16 GB GPU under a 52 GB cap
        self.assertEqual(upscale_plate.window_frames(251.0, 95.0, uhd, hd, 121), 121)  # one job on a 96 GB GPU with RAM
        self.assertEqual(upscale_plate.window_frames(64.0, 95.0, uhd, hd, 121), 69)
        self.assertEqual(upscale_plate.window_frames(24.0, 8.0, uhd, hd, 121), 21)


@unittest.skipUnless(plateio.av is not None, "PyAV missing")
class JoinedWindows(unittest.TestCase):
    def test_the_shared_frames_crossfade_from_one_window_to_the_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders = []
            for k, level in enumerate((0.2, 0.6)):
                folder = os.path.join(tmp, f"w{k:03}")
                os.makedirs(folder)
                plateio.write_pngs(lambda i, v=level: np.full((36, 64, 3), round(v * 65535), np.uint16),
                                   [os.path.join(folder, f"f_{n:05}_.png") for n in range(1, 7)])
                folders.append(folder)
            joined = plateio.join_windows(folders, 2)
            self.assertEqual(joined.shape, (10, 36, 64, 3))
            np.testing.assert_allclose(joined[:, 0, 0, 0], [0.2] * 4 + [0.2 * 2 / 3 + 0.6 / 3, 0.2 / 3 + 0.6 * 2 / 3] + [0.6] * 4, atol=1e-4)


if __name__ == "__main__":
    unittest.main()
