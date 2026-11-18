"""tests/hdr_plate.py finish --overlap: the overlap of SDR to HDR's tiled decode, set in the filled workflow."""
import json
import os
import sys
import unittest

from _env import ROOT, require

require("numpy", "scipy", "av", "OpenEXR")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402
import decode_cost  # noqa: E402
import hdr_plate  # noqa: E402


class Overlap(unittest.TestCase):
    def test_the_tiled_decode_of_the_hdr_workflow_takes_the_overlap_and_nothing_else_changes(self):
        prompt = build_workflows.fill("hdr", {"path": "plates/horse.mp4", "tile": 512})
        before = json.dumps(prompt, sort_keys=True)
        self.assertEqual(hdr_plate.decode_overlap(prompt, 128), 1)
        node = next(n for n in prompt.values() if n["class_type"] == "VAEDecodeTiled")
        self.assertEqual((node["inputs"]["tile_size"], node["inputs"]["overlap"]), (512, 128))
        node["inputs"]["overlap"] = 64  # the workflow's own overlap: the prompt is then the one filled
        self.assertEqual(json.dumps(prompt, sort_keys=True), before)


class Latent(unittest.TestCase):
    def test_save_latent_reads_the_latent_that_the_tiled_decode_reads(self):
        prompt = build_workflows.fill("hdr", {"path": "plates/horse.mp4"})
        key = hdr_plate.save_latent(prompt, "lat/latent")
        decode = next(n for n in prompt.values() if n["class_type"] == "VAEDecodeTiled")
        self.assertEqual(prompt[key], {"class_type": "SaveLatent", "inputs": {"samples": decode["inputs"]["samples"],
                                                                              "filename_prefix": "lat/latent"}})


class Ways(unittest.TestCase):
    def test_a_way_is_whole_core_s_tiles_or_the_vae_s_own_and_core_s_overlap_stops_at_a_quarter(self):
        self.assertEqual(decode_cost.way("whole"), {"name": "whole", "tile": 0, "overlap": 0, "own": False})
        self.assertEqual(decode_cost.way("512/128"), {"name": "512/128", "tile": 512, "overlap": 128, "own": False})
        self.assertEqual(decode_cost.way("256/128v"), {"name": "256/128v", "tile": 256, "overlap": 128, "own": True})
        with self.assertRaises(SystemExit):
            decode_cost.way("256/128")


if __name__ == "__main__":
    unittest.main()
