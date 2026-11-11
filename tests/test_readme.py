"""The repository's README against the code: its models and licences are those of web/models.json, its two download
commands exist, every file it names is in the repository, and its words follow the project's rules."""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import get_models  # noqa: E402


class Readme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            cls.text = fh.read()

    def test_every_model_with_its_source_and_its_licence(self):
        with open(os.path.join(ROOT, "web", "models.json"), encoding="utf-8") as fh:
            for m in json.load(fh)["models"]:
                self.assertIn(m["name"], self.text)
                self.assertIn(f"]({m['source']})", self.text, m["name"])
                self.assertIn(f"[{m['licence']}]({m['licence_url']})", self.text, m["name"])

    def test_the_two_download_commands_and_the_size_they_announce(self):
        for tool in ("get_models.py", "get_plates.py"):
            self.assertIn(f"python {tool}", self.text)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, tool)), tool)
        total = sum(get_models.SIZES[os.path.basename(path)] for _, path, _ in get_models.MODELS)
        self.assertIn(f"downloads what is missing: {total / 1e9:.0f} GB in all", self.text)

    def test_every_file_it_names_or_links_exists(self):
        named = set(re.findall(r"`((?:web|tools|tests)/[\w./-]+|[A-Z]+\.md)`", self.text)) | set(re.findall(r"\]\((?!https?:)([^)#]+)\)", self.text))
        named |= set(re.findall(r'src="(?!https?:)([^"]+)"', self.text))
        self.assertGreaterEqual(len(named), 6, named)
        for path in named:
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)

    def test_its_words(self):
        self.assertNotIn("\u2014", self.text, "no em dash")
        self.assertNotIn("RunPod", self.text, "Runpod")
        self.assertEqual(set(re.findall(r"(?i)ainvfx", self.text)), {"AInVFX", "ainvfx"}, "AInVFX, and ainvfx in addresses and ids")


if __name__ == "__main__":
    unittest.main()
