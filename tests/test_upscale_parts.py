"""The checks of a 4K set: tests/upscale_compare.py parts measures how far the 4K result is from plate x (1 - matte) +
layer x matte, and the GPU cases with « upscale » turn Finish > Upscale to 4K on through ui_live.py."""
import argparse
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
import gpu_matrix  # noqa: E402
import plateio  # noqa: E402
import upscale_compare  # noqa: E402


class Parts(unittest.TestCase):
    def test_a_set_that_adds_up_measures_under_one_step_and_a_shifted_layer_does_not(self):
        rng = np.random.default_rng(3)
        plate, layer = rng.random((2, 3, 48, 64, 3), np.float32)
        matte = np.zeros((3, 48, 64, 3), np.float32)
        matte[:, 12:36, 16:48] = 1.0
        matte[:, 10:38, 14:50] = np.maximum(matte[:, 10:38, 14:50], 0.5)  # a soft edge
        with tempfile.TemporaryDirectory() as root:
            def write(name, frames):
                os.makedirs(os.path.join(root, name), exist_ok=True)
                plateio.write_pngs(lambda i: np.round(np.clip(frames[i], 0, 1) * 65535).astype(np.uint16),
                                   [os.path.join(root, name, f"f_{i + 1:05d}_.png") for i in range(len(frames))])
            q = lambda a: np.round(a * 65535) / 65535  # noqa: E731  what a 16-bit frame holds
            write("plate", plate); write("layer", layer); write("matte", matte)
            write("export", q(plate) * (1 - q(matte)) + q(layer) * q(matte))
            good = upscale_compare.parts(root, root, frames=(2,), crop=16)
            self.assertEqual(good["frames"], 3)
            self.assertLess(good["max"], 1.0)
            self.assertTrue(os.path.exists(os.path.join(root, "parts_sheet.png")))
            for f in os.listdir(os.path.join(root, "export")):
                os.remove(os.path.join(root, "export", f))
            write("export", plate * (1 - matte) + np.roll(layer, 2, axis=2) * matte)
            self.assertGreater(upscale_compare.parts(root, root, frames=())["max"], 10.0)


class Cases(unittest.TestCase):
    def test_the_4k_cases_turn_the_row_on_and_stay_outside_quick_and_all(self):
        with open(os.path.join(HERE, "gpu_matrix.json")) as f:
            cases = json.load(f)
        for name in ("horse_cow_4k", "horse_erase_4k"):
            self.assertTrue(cases[name]["upscale"])
            self.assertNotIn(name, gpu_matrix.ALL)
            a = argparse.Namespace(url="http://127.0.0.1:8188", comfy="/c", channel="chrome", timeout=300, memory="", graph=False, hdr=False)
            self.assertIn("--upscale", gpu_matrix.command(a, {**cases[name], "strokes": [], "seed": 1}, "/tmp/x"))
        a = argparse.Namespace(url="u", comfy="/c", channel="chrome", timeout=300, memory="", graph=False, hdr=False)
        self.assertNotIn("--upscale", gpu_matrix.command(a, {"path": "plates/horse.mp4"}, "/tmp/x"))


if __name__ == "__main__":
    unittest.main()
