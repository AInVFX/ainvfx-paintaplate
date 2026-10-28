"""The page in headless Chromium against the mock ComfyUI (tests/ui_mock.py): undo and redo, selection, numbering, the
plate browser, the preview menu, the log. Needs playwright with Chromium; the ComfyUI job of the CI installs it, the
unit job does not, so a missing playwright skips here even in CI."""
import importlib.util
import os
import subprocess
import sys
import unittest

from _env import ROOT


@unittest.skipUnless(importlib.util.find_spec("playwright"), "pip install playwright && python -m playwright install chromium")
class UIMock(unittest.TestCase):
    def test_page_flow_against_the_mock(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "ui_mock.py")], capture_output=True, text=True, timeout=900)
        self.assertIn("UI MOCK PASSED", r.stdout, r.stdout[-3000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
