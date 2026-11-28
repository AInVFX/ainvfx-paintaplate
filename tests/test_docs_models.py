"""The README's table of model files: every file of get_models.MODELS has its row, with its link, its folder and its size, and
the table holds no other file."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import get_models  # noqa: E402


class ModelFiles(unittest.TestCase):
    def test_every_file_has_its_row(self):
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        for repo, path, folder in get_models.MODELS:
            name = os.path.basename(path)
            row = f"| [`{name}`](https://huggingface.co/{repo}/blob/main/{path}) | `models/{folder}/` | {get_models.size(get_models.SIZES[name])} |"
            self.assertIn(row, readme, f"{name}: its row in the README's table of model files")
        rows = re.findall(r"^\| \[`[^`]+`\]\(https://huggingface\.co/", readme, flags=re.M)
        self.assertEqual(len(rows), len(get_models.MODELS), "the table holds the files of get_models.MODELS, and no other")


if __name__ == "__main__":
    unittest.main()
