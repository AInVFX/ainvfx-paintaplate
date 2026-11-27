"""Upscale's rules exist twice: in web/logic.mjs for the page, and in tests/upscale_plate.py, which runs the same
workflows from a terminal. Both give the same sizes and windows for the same machines."""
import json
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402
import upscale_plate  # noqa: E402

PLATES = [(1920, 1080), (1080, 1920), (2048, 858), (1920, 1088), (1280, 723), (3840, 2160), (4096, 1716), (2560, 1440)]
MACHINES = [(52.0, 15.6), (175.1, 95.0), (64.0, 95.0), (24.0, 8.0), (128.0, 31.5), (96.0, 24.0)]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SameRules(unittest.TestCase):
    def page(self, expr):
        code = f"import('./web/logic.mjs').then((m) => console.log(JSON.stringify({expr})))"
        r = subprocess.run(["node", "--input-type=module", "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_the_constants_are_the_tools(self):
        u = self.page("m.UPSCALE")
        self.assertEqual((u["long"], u["chunk"], u["step"], u["modelRam"], u["copies"]),
                         (upscale_plate.LONG_SIDE, build_workflows.UPSCALE_CHUNK, upscale_plate.CHUNK_STEP,
                          upscale_plate.MODEL_RAM, upscale_plate.FRAME_COPIES))
        self.assertEqual((tuple(u["most"]), tuple(u["sizes"]), u["least"]), (upscale_plate.MOST, upscale_plate.SIZES, upscale_plate.LEAST))

    def test_every_size_asked_for_is_the_tools(self):
        asks = [("long", 3840), ("long", 2560), ("long", 1920), ("width", 2000), ("width", 2001), ("height", 1500), ("width", 5000), ("height", 700)]
        cases = [[w, h, side, px] for w, h in PLATES for side, px in asks]
        page = self.page(f"{json.dumps(cases)}.map(([w, h, side, px]) => m.upscaleTarget(w, h, {{ side, px }}))")
        for (w, h, side, px), target in zip(cases, page):
            self.assertEqual(tuple(target), upscale_plate.target_size(w, h, px, side), (w, h, side, px))

    def test_sizes_and_windows_are_the_tools(self):
        cases = [[w, h, ram, vram] for w, h in PLATES for ram, vram in MACHINES]
        page = self.page(f"{json.dumps(cases)}.map(([w, h, ram, vram]) => {{ const t = m.upscaleTarget(w, h); "
                         "const n = m.upscaleWindow(ram, vram, t, [w, h], 121); return [t, m.upscaleResize(w, h, t), n, m.upscaleWindows(121, n)]; })")
        for (w, h, ram, vram), (target, resize, window, windows) in zip(cases, page):
            t = upscale_plate.target_size(w, h)
            self.assertEqual(tuple(target), t, (w, h))
            self.assertEqual(resize, upscale_plate.resize_method(w, h, t), (w, h))
            self.assertEqual(window, upscale_plate.window_frames(ram, vram, t, (w, h), 121), (w, h, ram, vram))
            self.assertEqual([tuple(x) for x in windows], upscale_plate.windows(121, count=window, every=True))


if __name__ == "__main__":
    unittest.main()
