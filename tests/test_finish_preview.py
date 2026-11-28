"""--preview for tests/ui_live.py and tests/gpu_matrix.py: a GPU case chooses the Preview menu, stored before the page loads."""
import argparse
import json
import os
import sys
import unittest

from _env import ROOT

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import gpu_matrix  # noqa: E402
import ui_live  # noqa: E402


class Preview(unittest.TestCase):
    def test_each_choice_is_stored_as_the_page_keeps_it(self):
        self.assertEqual(ui_live.PREVIEW, {"off": "off", "latent": "latent", "half": "2", "quarter": "4"})
        self.assertEqual(ui_live.preview_script("half"), "sessionStorage.setItem('paintaplate.preview-menu', '2');")

    def test_a_gpu_case_passes_the_choice_to_ui_live_and_none_when_not_asked(self):
        with open(os.path.join(ROOT, "tests", "gpu_matrix.json")) as f:
            case = json.load(f)["horse_cow"]
        a = argparse.Namespace(url="http://127.0.0.1:8188", comfy="/comfy", channel="chrome", timeout=900, memory="", graph=False)
        self.assertNotIn("--preview", gpu_matrix.command(a, case, "/out/horse_cow"))
        cmd = gpu_matrix.command(argparse.Namespace(**vars(a), preview="half"), case, "/out/horse_cow")
        self.assertEqual(cmd[cmd.index("--preview") + 1], "half")


if __name__ == "__main__":
    unittest.main()
