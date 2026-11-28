"""tests/upscale_plate.py --decode-tile: the tile and the overlap of SeedVR2's decode, set in the filled workflow."""
import os
import sys
import unittest

from _env import ROOT

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402
import upscale_plate  # noqa: E402


class DecodeTile(unittest.TestCase):
    def test_seedvr2s_decode_takes_the_tile_and_its_encode_keeps_its_own(self):
        prompt = build_workflows.fill("upscale", {"shot": "plates/horse.mp4"})
        self.assertEqual(upscale_plate.decode_tiles(prompt, 4096, 128), 1)
        decode = next(n for n in prompt.values() if n["class_type"] == "VAEDecodeTiled")
        encode = next(n for n in prompt.values() if n["class_type"] == "VAEEncodeTiled")
        self.assertEqual((decode["inputs"]["tile_size"], decode["inputs"]["overlap"]), (4096, 128))
        self.assertEqual((encode["inputs"]["tile_size"], encode["inputs"]["overlap"]), (512, 128))


if __name__ == "__main__":
    unittest.main()
