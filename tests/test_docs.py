"""ARCHITECTURE.md and TESTING.md against the repository. Every file they name exists, the version and the pins they
state are the code's, and every flow, mock hook and section of app.mjs they name exists. With DOCS_COMPLETE=1 it also
checks the other way: every flow, hook and section is in the docs (the closing check before a version goes to main; the
workstreams add flows and hooks on their own branches, and only one of them edits the docs)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOT_OURS = {"MODELS.md": "a file of an export", "ocio_source_setup.py": "a file of OpenRV"}


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as fh:
        return fh.read()


def table(text, header):
    """The first cells of the table that opens with `header`, without their backticks."""
    rows = text[text.index(header):].split("\n\n")[0].splitlines()[2:]
    return [row.split("|")[1].strip().strip("`") for row in rows]


ARCHITECTURE, TESTING = read("ARCHITECTURE.md"), read("TESTING.md")
FLOWS = set(re.findall(r'"(\w+)": \w+_flow', read("tests", "ui_mock.py"))) | {n[:-3] for n in os.listdir(os.path.join(ROOT, "tests", "flows")) if n.endswith(".py")}
HOOKS = set(re.findall(r'add_(?:get|post)\("(/mock/\w+)"', read("tests", "mock_comfy.py")))
SECTIONS = [line[len("// ---------- "):] for line in read("web", "app.mjs").splitlines() if line.startswith("// ---------- ")]


class Docs(unittest.TestCase):
    def test_every_file_they_name_exists(self):
        files = {os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, "/")
                 for folder, _, names in os.walk(ROOT) if ".git" not in folder.split(os.sep) for name in names}
        known = files | {os.path.basename(f) for f in files} | set(NOT_OURS)
        for doc, text in (("ARCHITECTURE.md", ARCHITECTURE), ("TESTING.md", TESTING)):
            named = set(re.findall(r"`([\w./-]+\.(?:py|mjs|js|json|sh|md|yml|yaml|html|css|toml|txt))`", text))
            self.assertEqual(sorted(named - known), [], f"{doc} names files that are not in the repository")

    def test_the_version_and_the_pins_are_the_code_s(self):
        stated = re.search(r"It describes version (\d+\.\d+)\.\d+\.", ARCHITECTURE)
        version = re.search(r'^version = "(\d+\.\d+)\.\d+"', read("pyproject.toml"), re.M)
        self.assertEqual(stated and stated.group(1), version.group(1), "ARCHITECTURE.md says which version it describes: update it with the version")
        for pin in re.findall(r"^[A-Z_]+_PIN=(\w+)", read("tools", "pins.sh"), re.M):
            self.assertIn(f"`{pin}`", ARCHITECTURE, "section 13 gives the pins of tools/pins.sh")

    def test_what_they_name_exists(self):
        self.assertEqual(sorted(set(table(TESTING, "| Flow | What it proves |")) - FLOWS), [], "TESTING.md names flows that do not exist")
        self.assertEqual(sorted(set(re.findall(r"/mock/\w+", TESTING)) - HOOKS), [], "TESTING.md names mock routes that do not exist")
        gone = [row for row in table(ARCHITECTURE, "| Section | What it holds |") if not any(s.startswith(row) for s in SECTIONS)]
        self.assertEqual(gone, [], "ARCHITECTURE.md, section 11, names sections that web/app.mjs does not have")

    @unittest.skipUnless(os.environ.get("DOCS_COMPLETE") == "1", "the closing check before main: DOCS_COMPLETE=1")
    def test_everything_is_in_the_docs(self):
        self.assertEqual(sorted(FLOWS - set(table(TESTING, "| Flow | What it proves |"))), [], "TESTING.md: add a row for each of these flows")
        self.assertEqual(sorted(HOOKS - set(re.findall(r"/mock/\w+", TESTING))), [], "TESTING.md: add these mock routes to the table")
        rows = table(ARCHITECTURE, "| Section | What it holds |")
        self.assertEqual([s for s in SECTIONS if not any(s.startswith(row) for row in rows)], [], "ARCHITECTURE.md, section 11: add a row for each of these sections of web/app.mjs")


if __name__ == "__main__":
    unittest.main()
