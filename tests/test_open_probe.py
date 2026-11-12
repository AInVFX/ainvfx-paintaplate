"""tests/open_probe.py. Without a ComfyUI: the process that listens on a port and what it holds, read from a /proc and a
cgroup tree made for the test; ComfyUI's messages as a timeline; the table; the values the page sends with `ingest`. Then
one open of the mock ComfyUI's plate: the probe posts the page's ingest and reads the mock's own memory."""
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
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
from _env import ROOT, require  # noqa: E402

GB = 2 ** 30
SRGB = "sRGB Encoded Rec.709 (sRGB)"
TCP = ("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
       "   0: 0100007F:1FFC 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 4242 1 0000000000000000 100 0 0 10 0\n"
       "   1: 0100007F:1FFC 0100007F:C350 01 00000000:00000000 00:00000000 00000000  1000        0 4243 1 0000000000000000 20 4 30 10 -1\n")


def probe():
    for package in ("aiohttp", "numpy", "av", "OpenEXR"):  # the probe posts through tests/comfy_live.py, which reads plates
        require(package)
    import open_probe
    return open_probe


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class Memory(unittest.TestCase):
    """Port 8188 (0x1FFC) has a listening socket, held by process 900, and a browser's connection to it, held by process 77."""

    def setUp(self):
        self.p = probe()
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        self.proc, self.groups = os.path.join(root, "proc"), os.path.join(root, "cgroup")
        write(os.path.join(self.proc, "net", "tcp"), TCP)
        os.makedirs(os.path.join(self.proc, "self"))
        for pid, inode in ((77, 4243), (900, 4242)):
            os.makedirs(os.path.join(self.proc, str(pid), "fd"))
            os.symlink("/dev/null", os.path.join(self.proc, str(pid), "fd", "0"))
            os.symlink(f"socket:[{inode}]", os.path.join(self.proc, str(pid), "fd", "5"))
        self.status = os.path.join(self.proc, "900", "status")
        write(self.status, "Name:\tpython\nVmPeak:\t 9999999 kB\nVmHWM:\t 4194304 kB\nVmRSS:\t 2097152 kB\n")
        write(os.path.join(self.proc, "900", "cmdline"), "python\0main.py\0--enable-manager\0")
        write(os.path.join(self.proc, "900", "cgroup"), "0::/user.slice/run-1.scope\n")
        write(os.path.join(self.groups, "user.slice", "run-1.scope", "memory.current"), f"{3 * GB}\n")

    def test_the_process_that_listens(self):
        self.assertEqual(self.p.listener_pid(8188, self.proc), 900)
        self.assertIsNone(self.p.listener_pid(8189, self.proc), "nothing listens there")
        self.assertEqual(self.p.local_pid("http://localhost:8188/", self.proc), 900)
        self.assertIsNone(self.p.local_pid("https://abc-8188.proxy.runpod.net", self.proc), "another machine: /system_stats")

    def test_what_the_process_holds(self):
        source = self.p.Process(900, self.proc, self.groups)
        self.assertEqual(source.read(), (2 * GB, 3 * GB), "VmRSS, and the scope's memory.current")
        self.assertEqual(source.most(), 4 * GB, "VmHWM")
        self.assertIn("python main.py --enable-manager", source.name)

    def test_the_cgroup(self):
        write(os.path.join(self.proc, "900", "cgroup"), "0::/\n")  # inside a container
        self.assertIsNone(self.p.cgroup_file(900, self.proc, self.groups), "a machine's root keeps no count")
        write(os.path.join(self.groups, "memory.current"), f"{5 * GB}\n")
        self.assertEqual(self.p.Process(900, self.proc, self.groups).read(), (2 * GB, 5 * GB), "the container's count")

    def test_a_process_that_ends(self):
        source = self.p.Process(900, self.proc, self.groups)
        sampler = self.p.Sampler(source)
        sampler.start()
        time.sleep(0.4)
        write(self.status, "Name:\tpython\nState:\tZ (zombie)\n")  # killed: the kernel keeps the entry, with no memory
        sampler.join(3)
        self.assertFalse(sampler.is_alive(), "the readings stop by themselves")
        self.assertTrue(sampler.samples and all(s[1:] == (2 * GB, 3 * GB) for s in sampler.samples))


class Timeline(unittest.TestCase):
    PROMPT = {"1": {"class_type": "PaintAPlate_LoadPlate"}, "2": {"class_type": "PaintAPlate_ColorSpace"},
              "6": {"class_type": "ImageFromBatch"}}

    def job(self):
        job = probe().Job(self.PROMPT)
        job.id, job.posted = "abc", 0.2
        return job

    def test_comfyui_messages(self):
        job = self.job()
        feed = [({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 1}}}}, 0.25),
                ({"type": "executing", "data": {"node": "9", "prompt_id": "another"}}, 0.26),
                ({"type": "execution_start", "data": {"prompt_id": "abc", "timestamp": 1}}, 0.3),
                ({"type": "execution_cached", "data": {"nodes": ["6"], "prompt_id": "abc"}}, 0.3),
                ({"type": "executing", "data": {"node": "1", "display_node": "1", "prompt_id": "abc"}}, 0.3),
                ({"type": "progress", "data": {"value": 1, "max": 2, "prompt_id": "abc", "node": "1"}}, 0.7),
                ({"type": "executed", "data": {"node": "1", "output": {}, "prompt_id": "abc"}}, 1.1),
                ({"type": "executing", "data": {"node": "2", "display_node": "2", "prompt_id": "abc"}}, 1.1)]
        self.assertEqual([job.take(m, t) for m, t in feed], [False] * len(feed))
        self.assertTrue(job.take({"type": "execution_success", "data": {"prompt_id": "abc"}}, 1.6))
        self.assertEqual((job.events, job.cached, job.started, job.end, job.error), ([(0.3, "1"), (1.1, "2")], ["6"], 0.3, 1.6, None))
        self.assertEqual(job.node_at(1.0), "node 1 (PaintAPlate_LoadPlate)")
        self.assertIsNone(job.node_at(0.25))

    def test_a_job_that_fails_or_is_stopped(self):
        job = self.job()
        self.assertTrue(job.take({"type": "execution_error", "data": {"prompt_id": "abc", "node_type": "PaintAPlate_LoadPlate",
                                                                     "exception_message": "No plate at this path\n"}}, 1.0))
        self.assertEqual(job.error, "PaintAPlate_LoadPlate: No plate at this path")
        job = self.job()
        self.assertTrue(job.take({"type": "execution_interrupted", "data": {"prompt_id": "abc"}}, 1.0))
        self.assertEqual(job.error, "it was stopped")

    def test_the_table(self):
        p, job = probe(), self.job()
        job.events = [(0.3, "1"), (1.1, "2"), (1.2, "6")]  # node 2 lasts less than the time between two readings
        samples = [(t, held * GB, None) for t, held in ((0.0, 1), (0.25, 1), (0.5, 3), (0.75, 9), (1.0, 5), (1.25, 5), (1.5, 6), (1.75, 6))]
        lines = p.table(samples, job, job.posted, 1.6)
        self.assertEqual([line.split() for line in lines[1:4]], [["1", "PaintAPlate_LoadPlate", "1.0", "9.0", "5.0", "0.8"],
                                                                  ["2", "PaintAPlate_ColorSpace", "5.0", "5.0", "5.0", "0.1"],
                                                                  ["6", "ImageFromBatch", "5.0", "6.0", "6.0", "0.4"]])
        self.assertEqual(lines[4].split(), ["the", "whole", "job", "1.0", "9.0", "6.0", "1.4"])
        self.assertEqual(len(lines), 5)
        job.events = []  # a ComfyUI that names no node: the whole job still has its row
        self.assertEqual(p.table(samples, job, job.posted, 1.6)[1:], [lines[4]])

    def test_the_values_the_page_sends(self):
        p = probe()
        video = p.page_values("horse.mp4", {"kind": "video", "width": 1920, "height": 1080, "color_space": SRGB}, "paintaplate/probe_1")
        self.assertEqual(video, {"path": "horse.mp4", "config": "", "color_space": SRGB, "proxy_space": SRGB, "proxy_size": 1920,
                                 "movie_width": 1920, "movie_height": 1080, "prefix": "paintaplate/probe_1/hero",
                                 "video_prefix": "paintaplate/probe_1/proxy"})
        frames = p.page_values("shot/exr", {"kind": "sequence", "width": 5120, "height": 2701, "color_space": "ACEScg"}, "r")
        self.assertEqual([frames[k] for k in ("proxy_space", "proxy_size", "movie_width", "movie_height")], ["ACEScct", 4096, 4096, 2160],
                         "above the viewer's limit: 4096 x 2161, and a movie's sides are even")
        from build_workflows import load
        self.assertLessEqual(set(video), set(load("ingest")[1]), "every value is a slot of the ingest workflow")
        with open(os.path.join(ROOT, "web", "app.mjs")) as f:
            app = f.read()
        self.assertEqual(int(re.search(r"const NATIVE_SIDE = (\d+)", app).group(1)), p.NATIVE_SIDE)
        with open(os.path.join(ROOT, "web", "logic.mjs")) as f:
            self.assertIn(f'names.includes("{p.LOG_SPACE}")', f.read(), "the log space logic.viewerSpace picks")


class HeldOnce(unittest.TestCase):
    def test_no_node_of_the_open_makes_a_second_batch_of_the_plate(self):
        """Load Plate's frames go to three inputs: the first frame's ImageFromBatch, which copies one frame; Color Space's
        `peak_of`, which reads them; Save Movie's `images`, which takes one frame at a time. At 1.11.8 they went to a
        whole-plate Color Space and to an ImageFromBatch of every frame: 2.80 GB each for 1920 x 1080 x 121."""
        from build_workflows import load
        prompt = load("ingest")[0]
        plate = next(k for k, node in prompt.items() if node["class_type"] == "PaintAPlate_LoadPlate")
        takers = sorted((node["class_type"], key) for node in prompt.values() for key, v in node["inputs"].items() if v == [plate, 0])
        self.assertEqual(takers, [("ImageFromBatch", "image"), ("PaintAPlate_ColorSpace", "peak_of"), ("PaintAPlate_SaveMovie", "images")])
        self.assertEqual([node["inputs"]["length"] for node in prompt.values() if node["class_type"] == "ImageFromBatch"], [1])
        movie = next(node["inputs"] for node in prompt.values() if node["class_type"] == "PaintAPlate_SaveMovie")
        self.assertEqual(movie["frames"], [plate, 4], "the real frames, without the 8k+1 padding")


class Pictures(unittest.TestCase):
    def test_two_files_are_compared_by_their_pixels(self):
        probe()
        import numpy as np
        from PIL import Image, PngImagePlugin
        import comfy_live
        import plateio
        rng = np.random.default_rng(2)
        frames = [(rng.random((36, 64, 3)) * 255).astype(np.uint8) for _ in range(4)]

        def png(a, note):
            info, out = PngImagePlugin.PngInfo(), io.BytesIO()
            info.add_text("workflow", note)
            Image.fromarray(a).save(out, "PNG", pnginfo=info)
            return out.getvalue()
        one, other = png(frames[0], "a"), png(frames[0], "b" * 500)
        self.assertNotEqual(one, other)  # the bytes differ: each PNG carries its workflow
        self.assertEqual(comfy_live.frames_apart(one, other), 0)
        touched = frames[0].copy()
        touched[3, 5, 1] ^= 1
        self.assertEqual(comfy_live.frames_apart(one, png(touched, "a")), 1)
        level = int(frames[0][3, 5, 1])  # what a failed check says: how many frames, by how much, and where first
        self.assertEqual(comfy_live.differences(one, png(touched, "a")), (1, 1, 1, f"frame 0, sample (3, 5, 1): {level} and {level ^ 1}"))
        self.assertEqual(comfy_live.differences(one, other), (0, 1, 0, "a frame is missing"))
        folder = tempfile.mkdtemp()
        try:
            paths = [os.path.join(folder, f"{name}.mp4") for name in "abc"]
            for path, n in zip(paths, (4, 4, 3)):
                plateio.write_movie(lambda i: frames[i], n, path, 24.0, workers=2)
            self.assertEqual(comfy_live.frames_apart(paths[0], paths[1]), 0)
            self.assertEqual(comfy_live.frames_apart(paths[0], paths[2]), 1)  # a frame one movie lacks counts
            self.assertEqual(comfy_live.differences(paths[0], paths[2])[:2], (1, 4))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_the_live_tests_compare_the_open_on_movies_without_loss(self):
        """x264 does not always make the same movie from the same frames, so the live tests fill `ingest`, then set its
        Save Movie to crf 0: nothing else of the workflow changes."""
        probe()
        import comfy_live
        from build_workflows import fill
        values = {"path": "plates/horse.mp4", "prefix": "a/hero", "video_prefix": "a/proxy"}
        usual, exact = fill("ingest", values), comfy_live.lossless(fill("ingest", values))
        movie = next(k for k, node in usual.items() if node["class_type"] == "PaintAPlate_SaveMovie")
        self.assertEqual((usual[movie]["inputs"]["crf"], exact[movie]["inputs"]["crf"]), (12, 0))
        exact[movie]["inputs"]["crf"] = 12
        self.assertEqual(exact, usual)


class AgainstTheMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = probe()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.url, cls.root = f"http://127.0.0.1:{cls.port}", tempfile.mkdtemp()
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

    def run_probe(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.p.main([*args, "--url", self.url, "--settle", "0.5"])
        return code, out.getvalue()

    def test_an_open(self):
        readings = os.path.join(self.root, "readings.csv")
        code, text = self.run_probe("plates/desk.mp4", "--csv", readings)
        self.assertEqual(code, 0, text)
        self.assertIn(f"process {self.mock.pid} (", text, "the mock's own process, found from its port")
        self.assertIn("1280 x 704", text)
        self.assertRegex(text, r"the whole job +\d+\.\d +\d+\.\d +\d+\.\d +\d+\.\d\n")
        self.assertRegex(text, r"Peak: \d+\.\d GB, ")
        self.assertRegex(text, r"The most the process ever held \(VmHWM\): \d+\.\d GB")
        with urllib.request.urlopen(f"{self.url}/mock/posts") as r:
            self.assertEqual(json.load(r)[-1]["outputs"], ["hero", "proxy", "spec"], "the ingest, as the page posts it")
        with open(readings) as f:
            rows = f.read().splitlines()
        self.assertEqual(rows[0], "seconds,bytes,cgroup_bytes,node")
        self.assertGreater(len(rows), 4)

    def test_the_same_pictures_as_an_earlier_open(self):
        code, text = self.run_probe("plates/desk.mp4")
        self.assertEqual(code, 0, text)
        earlier = re.search(r"under (paintaplate/probe_\d+)\n", text).group(1)
        code, text = self.run_probe("plates/desk.mp4", "--same", earlier)
        self.assertEqual(code, 0, text)
        self.assertRegex(text, rf"The same pictures as under {earlier}, by their decoded pixels: hero\S+ and proxy\S+\n")
        code, text = self.run_probe("plates/desk.mp4", "--max-frames", "9", "--same", earlier)
        self.assertEqual(code, 1, text)
        self.assertRegex(text, rf"Not the same pictures as under {earlier}: \d+ frames differ in proxy\S+\n")
        code, text = self.run_probe("plates/desk.mp4", "--same", "paintaplate/probe_0")
        self.assertEqual(code, 1, text)
        self.assertIn("Not compared with paintaplate/probe_0: ", text)

    def test_a_plate_that_is_not_there(self):
        code, text = self.run_probe("plates/none.mp4")
        self.assertEqual(code, 1)
        self.assertIn("ComfyUI cannot read plates/none.mp4", text)

    def test_no_comfyui(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.p.main(["plates/desk.mp4", "--url", "http://127.0.0.1:9"])
        self.assertEqual(code, 1)
        self.assertIn("No ComfyUI answers at http://127.0.0.1:9", out.getvalue())


if __name__ == "__main__":
    unittest.main()
