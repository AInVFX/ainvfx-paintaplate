"""The six workflows the page runs: generated from tools/build_workflows.py, and valid against ComfyUI's source."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from _env import COMFY, LTX, ROOT

WORKFLOWS = os.path.join(ROOT, "web", "workflows")


class Workflows(unittest.TestCase):
    def test_generated_files_are_current(self):
        """web/workflows matches what tools/build_workflows.py writes: no hand edits, no stale files."""
        with tempfile.TemporaryDirectory() as out:
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_workflows.py")], check=True,
                           env={**os.environ, "PAINTAPLATE_WORKFLOWS_OUT": out}, capture_output=True)
            self.assertEqual(sorted(os.listdir(out)), sorted(os.listdir(WORKFLOWS)))
            for name in os.listdir(out):
                with open(os.path.join(out, name)) as a, open(os.path.join(WORKFLOWS, name)) as b:
                    self.assertEqual(json.load(a), json.load(b), f"{name} is stale: run tools/build_workflows.py")

    def test_every_slot_points_at_a_real_input(self):
        """Each named slot the page fills names a node and an input that exist in the prompt."""
        for name in os.listdir(WORKFLOWS):
            with open(os.path.join(WORKFLOWS, name)) as f:
                wf = json.load(f)
            for slot, targets in wf["slots"].items():
                for node, field in targets:
                    self.assertIn(node, wf["prompt"], f"{name}: slot {slot}")
                    if slot != "fit_mask":  # a link the page removes, not a value it sets
                        self.assertIn(field, wf["prompt"][node]["inputs"], f"{name}: slot {slot}")

    @unittest.skipUnless(COMFY and os.path.isdir(LTX), "set COMFYUI_DIR (and LTXVIDEO_DIR) to check against source")
    def test_classes_and_inputs_exist_in_source(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_workflows.py"), COMFY, LTX],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
