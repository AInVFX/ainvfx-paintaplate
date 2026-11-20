"""The README says what the Help says, in the same words: the first edit's steps follow the Help's Getting started tab, a
History row changes with its pencil, and Stop keeps the finished steps. It names the text prompt as the place to describe
an edit, in plain words."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as fh:
        return fh.read()


class ReadmeWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = read("README.md")
        page = read("web", "paintaplate.html")
        start = page[page.index('data-help="start"'):]
        cls.steps = re.findall(r"<li>([^<]*)</li>", start[:start.index("</ol>")])

    def test_the_first_edit_says_what_the_help_says(self):
        self.assertIn("Sequence files and folders of frames are supported.", self.steps[0])
        self.assertIn("Sequence files and folders of frames are supported.", self.readme)
        self.assertIn("the edit on the first frame followed by the shot. The Render panel shows each step as it runs", self.steps[2])
        self.assertIn("the edit on the first frame followed by the shot. The Render panel shows each step as it runs", self.readme)
        self.assertIn('Describe the edit in the text prompt, for example "a campfire".', self.readme)

    def test_history_and_stop_as_the_page_does_them(self):
        self.assertIn("click its pencil to change it", self.readme)
        self.assertIn("Finished steps are kept, and Enter continues from there.", self.readme)

    def test_plain_words(self):
        for phrase in ("at the top", "comes back behind", "goes on from", "holds every action", "It was seen"):
            self.assertNotIn(phrase, self.readme, phrase)


if __name__ == "__main__":
    unittest.main()
