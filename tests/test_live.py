"""A real ComfyUI on CPU, no model run: set COMFYUI_DIR to enable (see tools/ci_comfyui.sh).

Model files can be empty placeholders (tools/placeholders.py): model workflows are cancelled right after
ComfyUI validates them, and the browser test replaces them with stand-ins built from core nodes."""
import importlib.util
import os
import subprocess
import sys
import unittest

from _env import COMFY, PYTHON, ROOT

TESTS = os.path.join(ROOT, "tests")


def run(script, timeout):
    """The harness runs here; the ComfyUI it starts runs with COMFYUI_PYTHON."""
    r = subprocess.run([sys.executable, os.path.join(TESTS, script), "--comfy", COMFY, "--python", PYTHON],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


@unittest.skipUnless(COMFY, "set COMFYUI_DIR to a ComfyUI with this pack and ComfyUI-LTXVideo in custom_nodes")
class LiveComfyUI(unittest.TestCase):
    def test_workflows_validate_and_plates_round_trip(self):
        """ComfyUI loads the pack and serves the page; all workflows validate; EXR, ProRes and PNG plates export exactly."""
        out = run("comfy_live.py", 600)
        self.assertIn("ALL PASSED", out, out[-3000:])

    @unittest.skipUnless(importlib.util.find_spec("playwright"), "pip install playwright && playwright install chromium")
    def test_page_flow_in_a_browser(self):
        """Headless Chromium paints, erases, relights, picks options and exports through the real page."""
        out = run("ui_live.py", 900)
        self.assertIn("UI FLOW PASSED", out, out[-3000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
