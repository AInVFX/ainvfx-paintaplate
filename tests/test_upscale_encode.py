"""The full-size clean plate pass (cleanup) encodes its first stage whole by default: core's VAE Encode (Tiled) with a tile of
WHOLE px, larger than any working frame, encodes the frames in one piece."""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
COMFY = os.environ.get("COMFYUI_DIR")


def whole(path, pattern):
    with open(os.path.join(ROOT, path)) as f:
        return int(re.search(pattern, f.read(), re.M).group(1))


class FullSizeEncode(unittest.TestCase):
    def test_the_full_size_clean_plate_pass_encodes_whole_by_default(self):
        tile = whole("tools/build_workflows.py", r"^WHOLE = (\d+)")
        self.assertEqual(tile, whole("web/logic.mjs", r"^export const WHOLE = (\d+);"))
        for name in ("cleanup",):
            with open(os.path.join(ROOT, "web", "workflows", f"{name}.json")) as f:
                prompt = json.load(f)
            encodes = [n for n in prompt.values() if n.get("_meta", {}).get("slots", {}).get("tile_size") == "encode_tile"]
            self.assertEqual([(n["class_type"], n["inputs"]["tile_size"]) for n in encodes], [("VAEEncodeTiled", tile)], name)

    @unittest.skipUnless(COMFY, "COMFYUI_DIR: ComfyUI's source at the pin")
    def test_vae_encode_tiled_takes_the_whole_tile(self):
        with open(os.path.join(COMFY, "nodes.py")) as f:
            node = f.read().split("class VAEEncodeTiled", 1)[1].split("\nclass ", 1)[0]
        largest = int(re.search(r'"tile_size": \("INT", \{[^}]*"max": (\d+)', node).group(1))
        self.assertGreaterEqual(largest, whole("tools/build_workflows.py", r"^WHOLE = (\d+)"))


if __name__ == "__main__":
    unittest.main()
