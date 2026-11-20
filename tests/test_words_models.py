"""Each model's line in the Help's Models and licences tab (web/models.json) says what the model does in plain words, and
the README's Credits table gives the same line, word for word."""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as fh:
        return fh.read()


class ModelLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = json.loads(read("web", "models.json"))["models"]
        cls.readme = read("README.md")

    def test_each_line_says_what_the_model_does_in_plain_words(self):
        idioms = re.compile(r"\b(restores?|carries|takes|samples with)\b|painted on$", re.I)
        self.assertEqual([m["use"] for m in self.models if idioms.search(m["use"])], [])
        seed = next(m for m in self.models if m["id"].startswith("seedvr2") and "VAE" not in m["name"])
        self.assertTrue(seed["use"].startswith("Upscales the result"), seed["use"])

    def test_the_readme_gives_each_line_word_for_word(self):
        credits = self.readme[self.readme.index("| Model |"):] if "| Model |" in self.readme else self.readme
        self.assertEqual([m["use"] for m in self.models if m["use"] not in credits], [])


if __name__ == "__main__":
    unittest.main()
