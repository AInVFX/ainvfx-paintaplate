"""TESTING.md names every test file, and TESTING.md and ARCHITECTURE.md give the number of page shards that CI runs. The
first is the closing check before main (DOCS_COMPLETE=1): test files are added on branches, and this file follows them in
one edit."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as fh:
        return fh.read()


TESTING, ARCHITECTURE = read("TESTING.md"), read("ARCHITECTURE.md")
PARTS = len(re.search(r"shard: \[([\d, ]+)\]", read(".github", "workflows", "tests.yml")).group(1).split(","))


class Testing(unittest.TestCase):
    def test_the_documents_give_ci_s_shards(self):
        for name, text in (("TESTING.md", TESTING), ("ARCHITECTURE.md", ARCHITECTURE)):
            said = {WORDS.get(word, word) for word in re.findall(r"\bin (\w+) shards\b", text)}
            self.assertEqual(said, {PARTS}, f"{name}: CI runs the page tests in {PARTS} shards")

    @unittest.skipUnless(os.environ.get("DOCS_COMPLETE") == "1", "the closing check before main: DOCS_COMPLETE=1")
    def test_every_test_file_is_named(self):
        modules = [n[:-3] for n in os.listdir(TESTS) if n.startswith("test_") and n.endswith(".py")]
        files = [n for n in os.listdir(TESTS) if n.endswith((".py", ".json")) and not n.startswith("test_") and n != "__init__.py"]
        files += [n for n in os.listdir(os.path.join(TESTS, "js")) if n.endswith(".test.mjs")]
        lacking = [n for n in sorted(modules + files) if not re.search(rf"`(?:tests/(?:js/)?)?{re.escape(n)}\b", TESTING)]
        self.assertEqual(lacking, [], "TESTING.md: say what each of these proves")


if __name__ == "__main__":
    unittest.main()
