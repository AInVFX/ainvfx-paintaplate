"""The page: its modules, elements and workflows fit together, the JavaScript tests pass, and it shares the Python rules."""
import glob
import json
import os
import re
import subprocess
import sys
import unittest

from _env import ROOT, tool

WEB = os.path.join(ROOT, "web")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402


def read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return f.read()


def node():
    return tool("node", "install Node.js 20 or newer")


def modules():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(WEB, "*.mjs")))


class Page(unittest.TestCase):
    def test_elements_used_by_the_scripts_exist(self):
        used = {i for m in modules() for i in re.findall(r'\$\("#([\w-]+)', read(m))}
        defined = set(re.findall(r'id="([\w-]+)"', read("paintaplate.html")))
        self.assertTrue(used, "no element lookups found")
        self.assertEqual(sorted(used - defined), [])

    def test_imports_resolve_to_exported_names(self):
        for name in modules():
            for names, target in re.findall(r'import \{([^}]+)\} from "\./([\w.]+)"', read(name)):
                self.assertIn(target, modules(), f"{name} imports {target}")
                source = read(target)
                for sym in (s.strip() for s in names.split(",")):
                    self.assertRegex(source, rf"export (const|function|class|async function) {sym}\b", f"{name}: {sym} from {target}")

    def test_workflows_loaded_by_the_page_exist(self):
        names = re.findall(r'"(\w+)"', re.search(r"const WORKFLOWS = \[([^\]]+)\]", read("app.mjs")).group(1))
        self.assertEqual(sorted(names), sorted(build_workflows.NAMES))

    def test_menu_entry_does_not_load_the_app_into_the_graph_editor(self):
        """ComfyUI loads every .js file in web/ into the graph editor: the app's modules must stay .mjs."""
        self.assertEqual([f for f in os.listdir(WEB) if f.endswith(".js")], ["open.js"])

    def test_scripts_parse(self):
        for name in modules() + ["open.js"]:
            r = subprocess.run([node(), "--check", os.path.join(WEB, name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_javascript_unit_tests(self):
        """tests/js: the pure rules of logic.mjs and the frame cache of frames.mjs, in Node's own test runner."""
        r = subprocess.run([node(), "--test", *sorted(glob.glob(os.path.join(ROOT, "tests", "js", "*.test.mjs")))],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])

    def test_page_and_python_drop_the_same_optional_links(self):
        code = "import('./web/logic.mjs').then((m) => console.log(JSON.stringify(m.OPTIONAL)))"
        r = subprocess.run([node(), "--input-type=module", "-e", code], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({k: tuple(v) for k, v in json.loads(r.stdout).items()}, build_workflows.OPTIONAL)

    def test_page_and_python_share_the_ripple_sentence(self):
        """The shot prompt starts with one Ripple sentence: the page's (logic.RIPPLE) is the workflow's default."""
        code = "import('./web/logic.mjs').then((m) => console.log(JSON.stringify(m.RIPPLE)))"
        r = subprocess.run([node(), "--input-type=module", "-e", code], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(json.loads(r.stdout), build_workflows.RIPPLE_PROMPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
