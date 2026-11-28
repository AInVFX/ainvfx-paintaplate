"""The README says what the Help says, in the same words: the first edit's steps follow the Help's Getting started tab, and
the sentences on History's rows and on Stop are the Help's own, read from the page, so a change of the Help's words fails
here until the README follows. It names the text prompt as the place to describe an edit, in plain words."""
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
        cls.entries = {re.sub(r"<[^>]+>", "", dt).strip(): " ".join(re.sub(r"<[^>]+>", "", dd).split())
                       for dt, dd in re.findall(r"<dt>((?:(?!</dt>).)*)</dt>\s*<dd[^>]*>(.*?)</dd>", page, re.S)}
        cls.plain = cls.readme.replace("**", "").replace("`", "")  # the README's words, without its bold and code marks

    def test_the_first_edit_says_what_the_help_says(self):
        self.assertIn("Sequence files and folders of frames are supported.", self.steps[0])
        self.assertIn("Sequence files and folders of frames are supported.", self.readme)
        self.assertIn("make the edit on the first frame, then the shot. The Render panel shows each step as it runs", self.steps[2])
        self.assertIn("make the edit on the first frame, then the shot. The Render panel shows each step as it runs", self.readme)
        self.assertIn('Describe the edit in the text prompt, for example "a campfire".', self.readme)
        self.assertIn(re.search(r"A plate opens with [^.]*\.", self.steps[0]).group(0), self.plain)  # the length a plate opens with

    def test_history_and_stop_in_the_help_s_words(self):
        for entry, word in (("History", "pencil"), ("Stop", "Finished steps")):
            text = next(v for k, v in self.entries.items() if k.startswith(entry) and word in v)  # the Help's entry for it
            said = next(s for s in re.split(r"(?<=\.) ", text) if word in s)
            self.assertIn(said, self.plain, f"the README says the Help's {entry} sentence word for word")

    def test_plain_words(self):
        for phrase in ("at the top", "comes back behind", "goes on from", "holds every action", "It was seen"):
            self.assertNotIn(phrase, self.readme, phrase)


if __name__ == "__main__":
    unittest.main()
