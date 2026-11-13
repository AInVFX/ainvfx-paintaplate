"""PL5: comp, review and export composite with Composite Frames, one frame at a time, in place of core's Image Composite
Masked on the whole batch. The same pixels: mathops.composite against core's equation (comfy_extras/nodes_mask.py,
composite(), 0.44.2: mask * source + (1 - mask) * destination, with the mask at the source's size), written again here."""
import json
import os
import sys
import unittest

from _env import ROOT, require

require("numpy", "scipy")
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import mathops  # noqa: E402


def core(destination, source, mask):
    m = mask[..., None].astype(np.float32)
    return m * source + (1.0 - m) * destination


class CompositeFramesInTheComposite(unittest.TestCase):
    def test_the_same_pixels_as_core_and_the_untouched_ones_exact(self):
        rng = np.random.default_rng(0)
        for peak in (1.0, 7.4):  # an SDR plate, and the HDR plate's levels that PLA brings back
            dst, src = (rng.uniform(0, peak, (36, 64, 3)).astype(np.float32) for _ in range(2))
            mask = np.clip(rng.uniform(-0.5, 1.5, (36, 64)), 0, 1).astype(np.float32)
            got = mathops.composite(dst, src, mask)
            np.testing.assert_allclose(got, core(dst, src, mask), rtol=1e-6, atol=1e-7)
            self.assertTrue((got[mask == 0] == dst[mask == 0]).all())

    def test_comp_review_and_export_use_it(self):
        for name in ("comp", "review", "export"):
            with open(os.path.join(ROOT, "web", "workflows", f"{name}.json")) as f:
                nodes = [n for n in json.load(f).values() if isinstance(n, dict) and "class_type" in n]
            kinds = [n["class_type"] for n in nodes]
            self.assertNotIn("ImageCompositeMasked", kinds, name)
            final = [n for n in nodes if n["class_type"] == "PaintAPlate_CompositeFrames"]
            self.assertEqual([n["_meta"]["title"] for n in final], ["Composite"], name)


if __name__ == "__main__":
    unittest.main()
