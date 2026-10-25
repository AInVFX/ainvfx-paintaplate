"""Linters, when installed: pyflakes for Python, shellcheck for the pod setup script."""
import glob
import importlib.util
import os
import shutil
import subprocess
import sys
import unittest

from _env import ROOT

HAS_PYFLAKES = importlib.util.find_spec("pyflakes") is not None


class Lint(unittest.TestCase):
    @unittest.skipUnless(HAS_PYFLAKES, "pip install pyflakes")
    def test_pyflakes(self):
        files = [f for pattern in ("*.py", "tools/*.py", "tests/*.py") for f in glob.glob(os.path.join(ROOT, pattern))]
        r = subprocess.run([sys.executable, "-m", "pyflakes", *files], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    @unittest.skipUnless(shutil.which("shellcheck"), "install shellcheck (or pip install shellcheck-py)")
    def test_shellcheck(self):
        r = subprocess.run(["shellcheck", *glob.glob(os.path.join(ROOT, "tools", "*.sh"))], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
