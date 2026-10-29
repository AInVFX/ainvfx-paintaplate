"""The download route: which folders it reads, what each zip holds, and that it stays inside output/paintaplate."""
import asyncio
import os
import sys
import tempfile
import time
import types
import unittest
import zipfile

from _env import ROOT, require
require("aiohttp")

OUT = tempfile.mkdtemp(prefix="paintaplate_out_")
INPUT = tempfile.mkdtemp(prefix="paintaplate_in_")
TEMP = tempfile.mkdtemp(prefix="paintaplate_tmp_")
sys.modules["folder_paths"] = types.SimpleNamespace(get_output_directory=lambda: OUT, get_input_directory=lambda: INPUT,
                                                    get_temp_directory=lambda: TEMP)
sys.path.insert(0, ROOT)
import routes  # noqa: E402
import test_plateio  # noqa: E402
from aiohttp import web  # noqa: E402


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = os.path.join(OUT, "paintaplate", "abc", "v1")
        for i in (1, 2):
            touch(os.path.join(cls.folder, "export", f"shot.{1000 + i}.exr"))
            touch(os.path.join(cls.folder, "matte", f"matte_{i:05d}_.png"))
        touch(os.path.join(cls.folder, "comp_00001_.mp4"))
        touch(os.path.join(cls.folder, "raw_00001_.mp4"))
        touch(os.path.join(OUT, "secret.txt"), b"private")
        os.symlink(os.path.join(OUT, "secret.txt"), os.path.join(cls.folder, "export", "leak.exr"))
        touch(os.path.join(OUT, "paintaplate", "abc", "v2", "matte", "m.png"))  # a run without an export

    def test_only_run_folders_under_output_paintaplate(self):
        self.assertEqual(routes.run_folder("paintaplate/abc/v1"), self.folder)
        for bad in ("../..", "paintaplate", "paintaplate/../..", "/etc", "paintaplate/abc/v9", "secret.txt"):
            with self.assertRaises(FileNotFoundError, msg=bad):
                routes.run_folder(bad)

    def test_parts_of_a_run_laid_out_by_size(self):
        """The export's full-size review and the full-size pass win over what a preview size made."""
        with tempfile.TemporaryDirectory() as d:
            for rel in ("export/shot.1001.exr", "640x352/comp_00001_.mp4", "640x352/raw_00001_.mp4", "review_00001_.mp4",
                        "full/clean_00001_.mp4", "full/raw_00001_.mp4"):
                os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
                touch(os.path.join(d, rel))
            got = dict((arc, os.path.relpath(path, d)) for path, arc in routes.collect(d, ["export", "review", "shot"]))
            self.assertEqual(got["review.mp4"], "review_00001_.mp4")
            self.assertEqual(got["regenerated_shot.mp4"], os.path.join("full", "raw_00001_.mp4"))
            os.remove(os.path.join(d, "review_00001_.mp4"))  # before the export: the preview's composite
            got = dict((arc, os.path.relpath(path, d)) for path, arc in routes.collect(d, ["review"]))
            self.assertEqual(got["review.mp4"], os.path.join("640x352", "comp_00001_.mp4"))

    def test_parts_and_names(self):
        names = [arc for _, arc in routes.collect(self.folder, ["export", "matte", "review", "shot"])]
        self.assertEqual(names, ["export/shot.1001.exr", "export/shot.1002.exr", "matte/matte_00001_.png",
                                 "matte/matte_00002_.png", "review.mp4", "regenerated_shot.mp4"])
        self.assertNotIn("export/leak.exr", names)  # a symbolic link is never followed out of the run
        self.assertEqual(routes.zip_name("shot 010/../x", self.folder), "shot_010_.._x")

    def test_zip_is_built_once_then_rebuilt_when_files_change(self):
        path = routes.build_zip(self.folder, "shot", ["export", "review"])
        self.assertEqual(sorted(zipfile.ZipFile(path).namelist()), ["export/shot.1001.exr", "export/shot.1002.exr", "review.mp4"])
        first = os.path.getmtime(path)
        self.assertEqual(routes.build_zip(self.folder, "shot", ["export", "review"]), path)
        self.assertEqual(os.path.getmtime(path), first)  # reused while current
        time.sleep(0.02)
        touch(os.path.join(self.folder, "export", "shot.1003.exr"))
        self.assertIn("export/shot.1003.exr", zipfile.ZipFile(routes.build_zip(self.folder, "shot", ["export", "review"])).namelist())
        self.assertFalse([f for f in os.listdir(self.folder) if f.endswith(".part")])
        with self.assertRaises(FileNotFoundError):
            routes.build_zip(os.path.join(OUT, "paintaplate", "abc", "v2"), "x", ["export", "matte"])

    def test_handler(self):
        req = types.SimpleNamespace(query={"run": "paintaplate/abc/v1", "name": "shot", "parts": "export,bogus"})
        resp = asyncio.run(routes.download(req))
        self.assertIn('filename="shot.zip"', resp.headers["Content-Disposition"])
        with self.assertRaises(web.HTTPNotFound):
            asyncio.run(routes.download(types.SimpleNamespace(query={"run": "../../etc"})))
        app = types.SimpleNamespace(routes=web.RouteTableDef())
        routes.setup(app)
        self.assertEqual([r.path for r in app.routes], ["/paintaplate/download", "/paintaplate/plates", "/paintaplate/thumb", "/paintaplate/blank",
                                                          "/paintaplate/jobs/{key}", "/paintaplate/jobs/{key}", "/paintaplate/stat"])
        print("download route: folders, parts, symlinks, zip reuse, handler: ok")


class PlateBrowser(unittest.TestCase):
    """The Open dialog's list of input/plates and their thumbnails: videos and frame folders, nothing outside."""

    @classmethod
    def setUpClass(cls):
        require("av", "numpy", "PIL")
        cls.root = os.path.join(INPUT, "plates")
        os.makedirs(cls.root)
        test_plateio.make_prores(os.path.join(cls.root, "shot.mov"), n=5, w=96, h=64)
        os.makedirs(os.path.join(cls.root, "exr_shot"))
        test_plateio.make_exr_sequence(os.path.join(cls.root, "exr_shot"), n=3, h=36, w=64)
        os.makedirs(os.path.join(cls.root, "empty_folder"))
        touch(os.path.join(cls.root, "notes.txt"), b"not a plate")
        touch(os.path.join(INPUT, "elsewhere.txt"), b"private")
        os.symlink(os.path.join(INPUT, "elsewhere.txt"), os.path.join(cls.root, "link.mov"))

    def test_list_plates(self):
        items = routes.list_plates()
        self.assertEqual([i["path"] for i in items], ["plates/exr_shot", "plates/shot.mov"])  # no text file, empty folder or link
        mov = next(i for i in items if i["kind"] == "video")
        self.assertEqual((mov["width"], mov["height"], mov["frames"], mov["color_space"]), (96, 64, 5, "sRGB"))
        exr = next(i for i in items if i["kind"] == "sequence")
        self.assertEqual((exr["ext"], exr["frames"], exr["color_space"]), (".exr", 3, "linear ACEScg"))  # the test EXR carries AP1 chromaticities

    def test_thumbnails_are_jpegs_made_once(self):
        from PIL import Image
        for rel in ("plates/shot.mov", "plates/exr_shot"):
            path = routes.thumbnail(rel, width=48)
            with Image.open(path) as im:
                self.assertEqual((im.format, im.width), ("JPEG", 48))
            first = os.path.getmtime(path)
            time.sleep(0.02)
            self.assertEqual(routes.thumbnail(rel, width=48), path)
            self.assertEqual(os.path.getmtime(path), first)  # reused, not rewritten
        for bad in ("plates/notes.txt", "plates/link.mov", "../elsewhere.txt", "elsewhere.txt", "", os.path.join(INPUT, "plates", "shot.mov")):
            with self.assertRaises((FileNotFoundError, StopIteration, ValueError, OSError), msg=bad):
                routes.thumbnail(bad)

    def test_handlers(self):
        async def run():
            table = web.RouteTableDef()
            routes.setup(types.SimpleNamespace(routes=table))
            app = web.Application()
            app.add_routes(table)
            from aiohttp.test_utils import TestClient, TestServer
            async with TestClient(TestServer(app)) as client:
                r = await client.get("/paintaplate/plates")
                self.assertEqual(r.status, 200)
                self.assertEqual([i["name"] for i in await r.json()], ["exr_shot", "shot.mov"])
                r = await client.get("/paintaplate/thumb", params={"path": "plates/shot.mov"})
                self.assertEqual((r.status, r.headers["Content-Type"]), (200, "image/jpeg"))
                r = await client.get("/paintaplate/thumb", params={"path": "../elsewhere.txt"})
                self.assertEqual(r.status, 404)
        asyncio.run(run())



class BlankPlate(unittest.TestCase):
    def test_blank_plate_route(self):
        """A black canvas in input/paintaplate/blank: written once, refused outside 64-multiples, 8k + 1 frames and 1 to 120 fps."""
        require("av", "numpy")
        rel = routes.blank_plate(128, 64, 25, 17)
        self.assertEqual(rel, "paintaplate/blank/fluid_128x64_25fps_17f.mov")
        full = os.path.join(INPUT, rel)
        spec = routes.plateio.probe_plate(full)
        self.assertEqual((spec["codec"], spec["width"], spec["height"], spec["frames"], spec["fps"]), ("prores", 128, 64, 17, 25.0))
        first = os.path.getmtime(full)
        time.sleep(0.02)
        self.assertEqual(routes.blank_plate(128, 64, 25, 17), rel)
        self.assertEqual(os.path.getmtime(full), first)  # reused, not rewritten
        for bad in ((100, 64, 25, 17), (128, 64, 25, 16), (128, 64, 0, 17)):
            with self.assertRaises(ValueError, msg=str(bad)):
                routes.blank_plate(*bad)

        async def run():
            table = web.RouteTableDef()
            routes.setup(types.SimpleNamespace(routes=table))
            app = web.Application()
            app.add_routes(table)
            from aiohttp.test_utils import TestClient, TestServer
            async with TestClient(TestServer(app)) as client:
                r = await client.post("/paintaplate/blank", json={"width": 128, "height": 64, "fps": 25, "frames": 17})
                self.assertEqual((r.status, (await r.json())["path"]), (200, rel))
                r = await client.post("/paintaplate/blank", json={"width": 130, "height": 64, "fps": 25, "frames": 17})
                self.assertEqual(r.status, 400)
        asyncio.run(run())

if __name__ == "__main__":
    unittest.main(verbosity=2)


class JobIndex(unittest.TestCase):
    """A finished job's outputs, kept by the hash of its inputs, while its files stay in the output folder."""

    def test_a_record_holds_while_its_files_exist(self):
        frame = os.path.join(OUT, "paintaplate", "j1", "clean", "f_00001_.png")
        touch(frame)
        outputs = {"7": {"images": [{"filename": "f_00001_.png", "subfolder": "paintaplate/j1/clean", "type": "output"}]},
                   "9": {"text": ["a caption"]}}
        key = "a" * 40
        self.assertIsNone(routes.read_job(key))
        routes.write_job(key, outputs, "clean")
        self.assertEqual(routes.read_job(key)["outputs"], outputs)
        os.remove(frame)
        self.assertIsNone(routes.read_job(key), "a file gone: the job runs again")
        self.assertFalse(os.path.exists(routes.job_path(key)), "and its record goes")

    def test_keys_are_hashes_and_files_stay_in_the_output_folder(self):
        for bad in ("../x", "A" * 40, "ab", "g" * 40, None):
            with self.assertRaises(ValueError, msg=bad):
                routes.job_path(bad)
        touch(os.path.join(OUT, "paintaplate", "ok.png"))
        leak = {"filename": "leak.exr", "subfolder": "paintaplate/abc/v1/export", "type": "output"}  # a symbolic link
        for f in ({"filename": "secret.txt", "subfolder": "..", "type": "output"}, {"filename": "ok.png", "subfolder": "paintaplate", "type": "temp"},
                  {"filename": "passwd", "subfolder": "/etc", "type": "output"}, leak):
            with self.assertRaises(ValueError, msg=f):
                routes.write_job("b" * 40, {"1": {"images": [f]}})
        with self.assertRaises(ValueError):
            routes.write_job("b" * 40, {})

    def test_the_plate_stat_changes_with_the_plate(self):
        path = os.path.join(INPUT, "stat", "stat.mp4")
        touch(path, b"one")
        first = routes.plate_stat("stat/stat.mp4")
        self.assertEqual((first["files"], first["size"]), (1, 3))
        touch(path, b"other")
        os.utime(path, ns=(first["mtime"] + 10**9, first["mtime"] + 10**9))
        self.assertNotEqual(routes.plate_stat("stat/stat.mp4"), first)
        for i in (1, 2):
            touch(os.path.join(INPUT, "stat", "seq", f"f.{i:04d}.exr"), b"xx")
        self.assertEqual(routes.plate_stat("stat/seq")["files"], 2)
        for bad in ("../x", "stat/none.mp4", "output:../../etc"):
            with self.assertRaises(FileNotFoundError, msg=bad):
                routes.plate_stat(bad)
