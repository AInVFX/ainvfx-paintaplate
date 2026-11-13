"""tests/erase_probe.py without a GPU: its strokes, boxes and names, the page's own rules through Node, and one probe of the
mock ComfyUI, whose prompt writer answers with the request it got and whose Klein moves what a caption removes."""
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _env import ROOT, require, tool  # noqa: E402


def probe():
    require("numpy", "PIL", "av", "aiohttp")
    tool("node", "Node runs the page's rules (web/logic.mjs) for the probe")
    import erase_probe
    return erase_probe


class WhatThePageSends(unittest.TestCase):
    def test_the_sizes_and_passes_are_the_pages(self):
        p = probe()
        with open(os.path.join(ROOT, "web", "app.mjs")) as f:
            app = f.read()
        sides = re.search(r"const WORK_SIDE = (\d+), EDIT_SIDE = (\d+)", app)
        self.assertEqual((p.WORK_SIDE, p.EDIT_SIDE), (int(sides[1]), int(sides[2])))
        for name, values in (("QUICK", p.QUICK), ("FULL", p.FULL)):
            body = re.search(rf"const {name} = \{{([^}}]*)\}}", app)[1]
            for key, value in values.items():
                self.assertEqual(float(re.search(rf"{key}: (?:[^,]*\|\| )?([\d.]+)", body)[1]), value, f"{name}.{key}")
        for name in ("EDIT_GROW", "PAINT_GRID"):
            self.assertEqual(int(re.search(rf"const {name} = (\d+)", app)[1]), getattr(p, name), name)

    def test_the_barn_is_the_gpu_cases_stroke(self):
        p = probe()
        with open(os.path.join(HERE, "gpu_matrix.json")) as f:
            _, words, points, size, _ = json.load(f)[p.CASE]["strokes"][0]
        barn = p.default_strokes()[0]
        self.assertEqual((barn["words"], barn["points"], barn["size"]), (words, points, size))


class Strokes(unittest.TestCase):
    def test_a_stroke_from_the_command_line(self):
        p = probe()
        self.assertEqual(p.parse_stroke("post:0.9,0.5;0.9,0.8:30:the post"),
                         {"name": "post", "points": [[0.9, 0.5], [0.9, 0.8]], "size": 30.0, "words": "the post"})
        self.assertEqual(p.parse_stroke("p:0.1,0.2")["size"], 36)

    def test_the_brush_and_the_points_sam_gets(self):
        p = probe()
        s = {"name": "x", "points": [[0.25, 0.5], [0.75, 0.5]], "size": 20, "words": ""}
        self.assertTrue(19 <= p.stroke_mask(s, (400, 200))[:, 200].sum() <= 22)  # 20 pixels across
        pts = p.snap_points(s, (400, 200), (200, 100))  # 26 points along the drag: the 0th, 6th, 13th, 19th and 25th
        self.assertEqual([json.loads(v)[0]["x"] for v in pts.values()], [50, 74, 102, 126, 150])
        self.assertEqual({json.loads(v)[0]["y"] for v in pts.values()}, {50})
        self.assertEqual((p.jround(2.5), p.jround(-0.5), p.jround(12.5)), (3, 0, 13))


class Boxes(unittest.TestCase):
    def test_a_crop_and_back(self):
        p = probe()
        crop = p.crop_of([362, 721, 490, 1000])
        self.assertEqual(crop, [298, 582, 554, 1000])
        for box in ([362, 721, 490, 1000], [400, 800, 450, 900]):
            self.assertTrue(all(abs(u - v) <= 1 for u, v in zip(p.to_frame(p.to_crop(box, crop), crop), box)))
        rows = p.rows_to_frame([{"id": "barn_1", "src_bbox": [0, 0, 1000, 1000], "tgt_bbox": None}], crop)
        self.assertEqual(rows, [{"id": "barn_1", "src_bbox": crop, "tgt_bbox": None}])

    def test_bounds_and_the_tight_box(self):
        import numpy as np
        p = probe()
        m = np.zeros((100, 200), bool)
        m[20:40, 50:150] = True
        self.assertEqual(p.tight_box(m), [200, 250, 400, 750])
        self.assertEqual(p.bounds(np.zeros((10, 10), bool)), [0, 0, 1000, 1000])

    def test_masks_are_drawn_as_the_pages_canvas_draws_them(self):
        import numpy as np
        p = probe()
        m = np.zeros((1088, 1920), np.uint8)
        m[398:520, 1400:] = 255  # a barn's mask whose top is three quarters of the way down the grid's row 19
        rows = np.nonzero((p.resized(m, (96, 54)) > 32).any(1))[0]
        self.assertEqual(rows[0], 20)  # sampled at the cells' centres, as the page's canvas does: [362, ...] on 12 Nov

    def test_names(self):
        p = probe()
        self.assertEqual(p.name_of("The barn."), "barn")
        self.assertEqual(p.name_of('"A wooden fence post"\nIt stands in front.'), "wooden fence post")
        self.assertEqual(p.name_of(" \n"), "")


class PageRules(unittest.TestCase):
    def test_through_node(self):
        p = probe()
        size, ask, picked = p.page(
            ("fitSize", 1920, 1080, 768, 16),
            ("upsampleRequest", {"tool": "erase", "words": "", "bbox": [362, 721, 490, 1000], "boxes": [[362, 721, 490, 1000]]}),
            ("pickObjects", {"painted": p.raw([1, 1, 0, 0]), "points": [p.raw([1, 1, 1, 0]), p.raw([1, 1, 0, 0])],
                             "named": [], "area": 100}))
        self.assertEqual(size, [768, 432])
        self.assertEqual((ask["mode"], ask["locked"][0]["src_bbox"]), ("table", [362, 721, 490, 1000]))
        self.assertEqual(picked, [["points", 0], ["points", 1]])


class AgainstTheMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        probe()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.url, cls.root, cls.out = f"http://127.0.0.1:{cls.port}", tempfile.mkdtemp(), tempfile.mkdtemp()
        cls.mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_comfy.py"), "--plate", "--port", str(cls.port),
                                     "--root", cls.root, "--speed", "8"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        t0 = time.time()
        while True:
            try:
                urllib.request.urlopen(f"{cls.url}/system_stats", timeout=2).read()
                break
            except OSError:
                if time.time() - t0 > 60 or cls.mock.poll() is not None:
                    cls.tearDownClass()
                    raise RuntimeError("the mock ComfyUI did not start")
                time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.mock.terminate()
        cls.mock.wait(20)
        shutil.rmtree(cls.root, ignore_errors=True)
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_one_stroke_every_request(self):
        p = probe()
        said = io.StringIO()
        with redirect_stdout(said):
            p.main(["plates/desk.mp4", "--url", self.url, "--out", self.out,
                    "--stroke", "bottle:0.45,0.5;0.55,0.5:40"])
        with open(os.path.join(self.out, "answers.json")) as f:
            o = json.load(f)["strokes"][0]
        self.assertEqual(list(o["requests"]), list(p.REQUESTS))
        self.assertTrue(o["requests"]["own"]["caption"].startswith("Remove the object inside <obj_1> completely"))
        # the mock's writer answers with the request, which cites <obj_1>: the page keeps it
        for req in ("page", "wide", "dimmed", "crop", "as_words"):
            self.assertFalse(o["requests"][req]["refused"], req)
            self.assertIn("<obj_1>", o["requests"][req]["caption"], req)
        # the crop's answer carries the page's own boxes on the frame, not the crop's
        self.assertIn(json.dumps(o["paths"]["page"]["chosen"]["boxes"][0], separators=(", ", ": ")).replace(" ", "")[1:-1],
                      o["requests"]["crop"]["caption"].replace(" ", ""))
        # one Klein job per mask and caption that differ; the mock's Klein moves what it removes by 51 levels, and SAM finds the same discs
        self.assertEqual(len(o["edits"]), len({f"{r['path']}|{r['caption']}" for r in o["requests"].values()}))
        # as_words names the object, then runs as if the name had been typed: SAM 3.1 by that name, and a mask of its own
        self.assertEqual((o["requests"]["as_words"]["path"], o["paths"]["name"]["words"]), ("name", o["object"]))
        self.assertIn(f"Remove the {o['object']} <obj_1>", o["requests"]["as_words"]["request"])
        self.assertEqual(o["paths"]["page"]["chosen"]["boxes"], [o["paths"]["page"]["core"]])  # no words, one part: the core box
        for cap, e in o["edits"].items():
            self.assertGreater(e["share"][0], 0.5, cap[:60])
            self.assertEqual(e["sam"], 1.0)
            self.assertFalse(e["check"]["left"], cap[:60])  # the mock's Klein removes what it is asked to: the page's check agrees
            self.assertTrue(os.path.exists(os.path.join(self.out, e["after"])))
        with open(os.path.join(self.out, "report.md")) as f:
            report = f.read()
        for req in p.REQUESTS:
            self.assertIn(f"| {req} |", report)
        from PIL import Image
        with Image.open(os.path.join(self.out, "sheet.png")) as sheet:
            self.assertEqual(sheet.size[0], 8 + (len(p.REQUESTS) + 1) * (384 + 8))
        self.assertIn("Written to", said.getvalue())


if __name__ == "__main__":
    unittest.main()
