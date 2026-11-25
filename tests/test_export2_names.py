"""One rule names an export's zip, its files and its log (logic.fileStem on the page, routes.zip_name on the route): a name
with a space, a dot, a slash or a letter outside ASCII comes out the same from both."""
import json
import os
import shutil
import subprocess
import sys
import unittest

from _env import ROOT

sys.path.insert(0, ROOT)
from test_export_source import load_routes  # noqa: E402

NAMES = ["Désk shot.01", "shot 010/../x", "  über / plate  ", "a  b", "_x_", "plate-01.v2", "日本の皿"]


@unittest.skipIf(shutil.which("node") is None, "Node runs the page's rule")
class OneRule(unittest.TestCase):
    def test_the_page_and_the_route_name_a_file_alike(self):
        script = f"import {{ fileStem }} from {json.dumps('file://' + os.path.join(ROOT, 'web', 'logic.mjs'))}; console.log(JSON.stringify({json.dumps(NAMES)}.map(fileStem)));"
        page = json.loads(subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)
        route = [load_routes().zip_name(n, "/tmp/paintaplate/x/v1") for n in NAMES]
        self.assertEqual(page[:-1], route[:-1])
        self.assertEqual((page[-1], route[-1]), ("", "v1"))  # nothing left of the name: the page says no_plate, the route the run's folder
        print("one rule:", dict(zip(NAMES, route)))


if __name__ == "__main__":
    unittest.main()
