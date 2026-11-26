"""One word for what the viewer displays: « displayed », in every file of the repository, the code's comments and the
documents included. The word « on » followed by the word « show » appears nowhere, even split by a line break or a comment
marker."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = (".py", ".mjs", ".js", ".json", ".md", ".html", ".css", ".sh", ".yml", ".yaml", ".toml", ".txt")
PHRASE = re.compile(r"(?:\b|(?<=\\b))on(?:\s|//|#)+show\b", re.I)  # also after a regular expression's \b


class Displayed(unittest.TestCase):
    def test_no_file_says_on_show(self):
        found = []
        for folder, dirs, names in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
            for name in names:
                if name.endswith(TEXT):
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                    found += [f"{os.path.relpath(path, ROOT)}:{text.count(chr(10), 0, m.start()) + 1}" for m in PHRASE.finditer(text)]
        self.assertEqual(found, [], "say « displayed »")


if __name__ == "__main__":
    unittest.main()
