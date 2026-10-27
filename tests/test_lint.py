"""Linters: pyflakes for the Python, shellcheck for the setup scripts."""
import glob
import os
import subprocess
import sys
import unittest

from _env import INSTALL, ROOT, require, tool


class Lint(unittest.TestCase):
    def test_pyflakes(self):
        require("pyflakes")
        files = [f for pattern in ("*.py", "tools/*.py", "tests/*.py") for f in glob.glob(os.path.join(ROOT, pattern))]
        r = subprocess.run([sys.executable, "-m", "pyflakes", *files], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_shellcheck(self):
        shellcheck = tool("shellcheck", f"{INSTALL} (it brings shellcheck-py), or install shellcheck")
        r = subprocess.run([shellcheck, *glob.glob(os.path.join(ROOT, "tools", "*.sh"))], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
