"""The light probe (tests/light_probe.py): its sets and its plan, then one run against the mock ComfyUI."""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from contextlib import redirect_stdout

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def probe():
    sys.path.insert(0, HERE)
    import light_probe
    return light_probe


class Offline(unittest.TestCase):
    def test_a_set_from_the_command_line(self):
        p = probe()
        self.assertEqual(p.parse_set("glow|a soft glow|#ffb060:0.2,0.25;0.22,0.27:60|#000000:0.1,0.1;0.2,0.2:100"),
                         ("glow", ("a soft glow", [("#ffb060", [(0.2, 0.25), (0.22, 0.27)], 60.0),
                                                   ("#000000", [(0.1, 0.1), (0.2, 0.2)], 100.0)])))

    def test_the_plan_is_drawn_as_the_pages(self):
        # app.lightPlan: grey, the shade in black under the light, solid colours; the lights' boxes leave the shade out
        p = probe()
        strokes = [("#ffb060", [(0.5, 0.5), (0.6, 0.5)], 192), ("#000000", [(0.3, 0.5), (0.55, 0.5)], 192)]
        plan, lights = p.plan_of(strokes, (96, 54), [False, True])
        self.assertEqual(tuple(plan[2, 2]), p.rgb(p.PLAN_GREY))
        self.assertEqual(tuple(plan[27, 52]), (0xff, 0xb0, 0x60))  # where both are painted, the light is on top
        self.assertEqual(tuple(plan[27, 30]), (0, 0, 0))
        self.assertTrue(lights[27, 52] and not lights[27, 30])


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

    def test_two_sets_every_way(self):
        p = probe()
        said = io.StringIO()
        with redirect_stdout(said):
            p.main(["plates/desk.mp4", "--url", self.url, "--out", self.out, "--sets", "lamp,candle"])
        with open(os.path.join(self.out, "answers.json")) as f:
            sets = {s["set"]: s for s in json.load(f)["sets"]}
        self.assertEqual(sorted(sets), ["candle", "lamp"])
        lamp, candle = sets["lamp"]["ways"], sets["candle"]["ways"]
        self.assertEqual(sorted(lamp), sorted(p.WAYS))
        for way, w in lamp.items():
            self.assertTrue(os.path.exists(os.path.join(self.out, w["after"])), way)
            self.assertGreater(w["edges"], 0.5, way)
        self.assertTrue(lamp["today"]["caption"].startswith("Relight the first image with the light planned in the second image"))
        self.assertTrue(lamp["intent"]["caption"].startswith("Relight the whole scene with new light"))
        self.assertEqual(lamp["intent_plan"]["caption"], lamp["intent"]["caption"])
        self.assertEqual(lamp["words"]["request"], "a warm table lamp")  # the mock's writer gives the request back
        self.assertEqual(lamp["intent_writer"]["request"], sets["lamp"]["intent"])
        self.assertEqual(candle["words"], {"skipped": "no words"})
        self.assertIn("The top left of the frame falls into deep shadow.", sets["candle"]["intent"])
        from PIL import Image
        with Image.open(os.path.join(self.out, "sheet_desk_lamp.png")) as sheet:
            self.assertEqual(sheet.size[0], 8 + (2 + len(p.WAYS)) * (p.TILE + 8))
        with open(os.path.join(self.out, "report.md")) as f:
            report = f.read()
        for way in p.WAYS:
            self.assertIn(f"| {way} |", report)
        self.assertIn("Written to", said.getvalue())
        self.assertTrue(np.isfinite(lamp["intent"]["lift"][0]))


if __name__ == "__main__":
    unittest.main()
