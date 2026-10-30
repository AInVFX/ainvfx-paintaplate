"""The pack's Registry metadata in pyproject.toml: what the Comfy Registry and ComfyUI Manager read and show."""
import os
import tomllib
import unittest

from _env import ROOT


class Registry(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            self.project = tomllib.load(f)["project"]

    def test_dependencies_listed_as_requirements_txt_lists_them(self):
        """The Registry reads only a static list: a dynamic one showed no dependencies (0.5.0, 29 Oct 2026). ComfyUI
        Manager and the Registry's node scan install requirements.txt."""
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
            wanted = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        self.assertEqual(self.project["dependencies"], wanted)
        self.assertNotIn("dynamic", self.project)

    def test_no_accelerator_required(self):
        """The nodes run on a CPU, as the CI runs them. A GPU classifier made ComfyUI Manager report a conflict on any
        machine without that GPU (29 Oct 2026)."""
        self.assertEqual([c for c in self.project.get("classifiers", []) if c.startswith("Environment ::")], [])

    def test_semantic_version(self):
        self.assertRegex(self.project["version"], r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
