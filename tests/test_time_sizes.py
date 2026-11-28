"""One home per ceiling of size and length (plateio): the frames route stops at the page's NATIVE_SIDE; every node takes
its largest side and its most frames from plateio; and the page's LENGTH.most is the largest 8k + 1 count within them."""
import os
import re
import subprocess
import sys
import unittest

from _env import ROOT, tool

sys.path.insert(0, ROOT)
import plateio  # noqa: E402


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class OneHome(unittest.TestCase):
    def test_the_viewer_and_the_frames_route_stop_at_one_side(self):
        page = int(re.search(r"^const NATIVE_SIDE = (\d+);", read("web/app.mjs"), re.M).group(1))
        self.assertEqual(page, plateio.NATIVE_SIDE, "web/app.mjs's NATIVE_SIDE and plateio's")
        self.assertIn("min(max(64, side), plateio.NATIVE_SIDE)", read("routes.py"), "the frames route reads plateio's")

    def test_every_node_takes_its_ceilings_from_plateio(self):
        src = read("nodes.py")
        bounds = re.findall(r'io\.Int\.Input\("(\w+)"[^)\n]*?max=(\w+)', src)
        sized = [(name, top) for name, top in bounds if name in ("width", "height", "largest_size", "frames", "max_frames", "count")]
        self.assertTrue(sized, "the nodes' inputs of size and length")
        mine = [(name, top) for name, top in sized if top not in ("MOST_SIDE", "MOST_FRAMES")]
        self.assertEqual(mine, [], "a node's ceiling of frames or size written as a number of its own")
        self.assertEqual({top for name, top in sized if name in ("width", "height", "largest_size")}, {"MOST_SIDE"})
        self.assertEqual({top for name, top in sized if name in ("frames", "max_frames", "count")}, {"MOST_FRAMES"})

    def test_the_page_s_most_frames_is_the_largest_count_ltx_takes_within_the_nodes(self):
        code = "import { LENGTH } from './web/logic.mjs'; console.log(LENGTH.most);"
        r = subprocess.run([tool("node", "install Node.js 20 or newer"), "--input-type=module", "-e", code], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(int(r.stdout), plateio.MOST_FRAMES - (plateio.MOST_FRAMES - 1) % 8)


if __name__ == "__main__":
    unittest.main()
