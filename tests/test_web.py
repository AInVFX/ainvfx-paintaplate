"""The page: every element and workflow the script uses exists, and the scripts parse."""
import os
import re
import shutil
import subprocess
import unittest

from _env import ROOT

WEB = os.path.join(ROOT, "web")


def read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return f.read()


class Page(unittest.TestCase):
    def test_elements_used_by_the_script_exist(self):
        used = set(re.findall(r'\$\("#([\w-]+)', read("app.mjs")))
        defined = set(re.findall(r'id="([\w-]+)"', read("paintaplate.html")))
        self.assertTrue(used, "no element lookups found")
        self.assertEqual(sorted(used - defined), [])

    def test_workflows_loaded_by_the_page_exist(self):
        names = re.search(r'for \(const name of \[([^\]]+)\]\) WF\[name\]', read("app.mjs")).group(1)
        for name in re.findall(r'"(\w+)"', names):
            self.assertTrue(os.path.isfile(os.path.join(WEB, "workflows", f"{name}.json")), name)

    def test_menu_entry_does_not_load_the_app_into_the_graph_editor(self):
        """ComfyUI loads every .js file in web/ into the graph editor: the app itself must stay .mjs."""
        js = [f for f in os.listdir(WEB) if f.endswith(".js")]
        self.assertEqual(js, ["open.js"])

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_scripts_parse(self):
        for name in ("app.mjs", "open.js"):
            r = subprocess.run(["node", "--check", os.path.join(WEB, name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
