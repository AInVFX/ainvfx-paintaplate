"""tests/tos_plate.py against a local server: the frames and their credit, a second run that fetches nothing, a frame the
server lacks, and Load Plate's reader on the fetched 1920 x 1012 frames."""
import functools
import http.server
import io
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout

import numpy as np
import OpenEXR

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import plateio  # noqa: E402
import tos_plate  # noqa: E402


class Served(http.server.SimpleHTTPRequestHandler):
    asked = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Served.asked.append(self.path)
        super().do_GET()


def exr(path, width=1920, height=1012):
    """A half-float EXR frame of mid-grey, as the shot's frames are stored."""
    with OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage},
                      {"RGB": np.full((height, width, 3), 0.18, np.float16)}) as f:
        f.write(path)


class TosPlate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = tempfile.mkdtemp(prefix="tos_source_")
        for number in (480, 481, 482):
            exr(os.path.join(cls.source, tos_plate.name(number)))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Served, directory=cls.source))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def comfy_folder(self):
        comfy = tempfile.mkdtemp(prefix="tos_comfy_")
        os.makedirs(os.path.join(comfy, "input"))
        return comfy, os.path.join(comfy, "input", "plates", "tos_05_4a")

    def run_tool(self, comfy, frames):
        out = io.StringIO()
        with redirect_stdout(out):
            code = tos_plate.main(["--comfy", comfy, "--url", self.url, "--frames", frames])
        return code, out.getvalue()

    def test_the_frames_their_credit_and_a_second_run_that_fetches_nothing(self):
        comfy, folder = self.comfy_folder()
        code, text = self.run_tool(comfy, "480-482")
        self.assertEqual(code, 0, text)
        self.assertEqual(sorted(os.listdir(folder)), ["05_4a_00480.exr", "05_4a_00481.exr", "05_4a_00482.exr", "CREDIT.txt"])
        with open(os.path.join(folder, "CREDIT.txt")) as f:
            self.assertIn("(CC) Blender Foundation | mango.blender.org", f.read())
        self.assertIn("Plate ready: 3 frames in ", text)
        Served.asked.clear()
        code, text = self.run_tool(comfy, "480-482")
        self.assertEqual((code, Served.asked), (0, []), text)
        self.assertIn("Fetched now: 0 frames, 0 MB", text)

    def test_a_frame_the_server_lacks(self):
        comfy, folder = self.comfy_folder()
        code, text = self.run_tool(comfy, "482-483")
        self.assertEqual(code, 1, text)
        self.assertIn("Frame 483 not fetched (HTTP Error 404", text)
        self.assertEqual(sorted(os.listdir(folder)), ["05_4a_00482.exr", "CREDIT.txt"])

    def test_no_comfyui_folder(self):
        code, text = self.run_tool(tempfile.mkdtemp(), "480-480")
        self.assertEqual(code, 1, text)
        self.assertIn("ComfyUI's input folder not found: ", text)

    def test_load_plate_reads_the_frames_at_their_1920_x_1012(self):
        comfy, folder = self.comfy_folder()
        self.run_tool(comfy, "480-482")
        files = plateio.sequence_frames(folder)[0]
        rgb, _, count = plateio.decode_frames(files, True, 2, None)
        self.assertEqual((count, rgb.shape[1:]), (3, (1012, 1920, 3)))
        self.assertAlmostEqual(float(rgb[0, 0, 0, 0]), 0.18, places=3)


if __name__ == "__main__":
    unittest.main()
