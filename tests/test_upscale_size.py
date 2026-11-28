"""Finish > Upscale at a size in the GPU tools: a case's size reaches ui_live.py's --upscale, and the cases that prove
the sizes ask for theirs."""
import argparse
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpu_matrix  # noqa: E402


class CaseSizes(unittest.TestCase):
    def test_a_case_hands_its_size_to_the_page(self):
        a = argparse.Namespace(url="http://127.0.0.1:8188", comfy="/comfy", channel="chrome", timeout=900, memory="", graph=False)
        cases = gpu_matrix.load_cases()
        asked = {name: [x for x in gpu_matrix.command(a, cases[name], f"/out/{name}") if x.startswith("--upscale")]
                 for name in ("horse_cow", "horse_cow_4k", "horse_cow_2560", "horse_cow_own", "horse_erase_2000", "fluid_720_4k", "uhd_light_4k", "hdr_cow_4k")}
        self.assertEqual(asked, {"horse_cow": [], "horse_cow_4k": ["--upscale"], "horse_cow_2560": ["--upscale=2560"],
                                 "horse_cow_own": ["--upscale=1920"], "horse_erase_2000": ["--upscale=2000"],
                                 "fluid_720_4k": ["--upscale"], "uhd_light_4k": ["--upscale"], "hdr_cow_4k": ["--upscale"]})
        self.assertIn("--fluid", gpu_matrix.command(a, cases["fluid_720_4k"], "/out/fluid_720_4k"))


if __name__ == "__main__":
    unittest.main()
