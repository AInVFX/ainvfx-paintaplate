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
        self.assertEqual(routes.folders.run_folder("paintaplate/abc/v1"), self.folder)
        elsewhere = tempfile.mkdtemp(prefix="paintaplate_elsewhere_")
        os.makedirs(os.path.join(elsewhere, "export"))
        os.symlink(elsewhere, os.path.join(OUT, "paintaplate", "linked"))  # a render folder linked out of output/paintaplate
        for bad in ("../..", "paintaplate", "paintaplate/../..", "/etc", "paintaplate/abc/v9", "secret.txt", "paintaplate/linked"):
            with self.assertRaises(FileNotFoundError, msg=bad):
                routes.folders.run_folder(bad)

    def test_an_output_folder_that_is_a_link(self):
        """ComfyUI's output folder may itself be a symbolic link, to a bigger disk: its renders still download."""
        alias = os.path.join(tempfile.mkdtemp(prefix="paintaplate_alias_"), "output")
        os.symlink(OUT, alias)
        stub = sys.modules["folder_paths"]
        stub.get_output_directory = lambda: alias
        try:
            got = [arc for _, arc in routes.collect(routes.folders.run_folder("paintaplate/abc/v1"), ["export", "matte"])]
        finally:
            stub.get_output_directory = lambda: OUT
        self.assertEqual(got, [arc for _, arc in routes.collect(self.folder, ["export", "matte"])])
        self.assertIn("export/shot.1001.exr", got)
        self.assertNotIn("export/leak.exr", got)

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
        self.assertEqual([r.path for r in app.routes], ["/paintaplate/download", "/paintaplate/browse", "/paintaplate/thumb",
                         "/paintaplate/blank", "/paintaplate/jobs/{key}", "/paintaplate/jobs/{key}", "/paintaplate/stat",
                         "/paintaplate/frames", "/paintaplate/scenes", "/paintaplate/scenes/{name}", "/paintaplate/scenes/{name}",
                         "/paintaplate/ocio", "/paintaplate/ocio/shader", "/paintaplate/version"])
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
        from PIL import Image
        os.makedirs(os.path.join(OUT, "video"), exist_ok=True)
        import numpy as np, plateio
        plateio.write_movie(lambda i: np.full((32, 64, 3), 40 * i, np.uint8), 3, os.path.join(OUT, "video", "ComfyUI_00001_.mp4"), 24)
        for k in range(3):
            Image.new("RGB", (96, 48), (60 * k, 90, 30)).save(os.path.join(OUT, f"ComfyUI_{k + 1:05d}_.png"))
        frames = [Image.new("RGB", (96, 48), (40 * k, 0, 0)) for k in range(4)]
        frames[0].save(os.path.join(OUT, "anim_00001_.webp"), save_all=True, append_images=frames[1:], duration=40)

    def test_browse_lists_folders_without_opening_files(self):
        """input and output, subfolders, videos, frame patterns; no text file, no link, nothing outside."""
        got = routes.browse("plates")
        self.assertEqual((got["path"], got["parent"]), ("plates", ""))
        self.assertEqual(sorted((i["kind"], i["path"]) for i in got["items"]),
                         [("folder", "plates/empty_folder"), ("folder", "plates/exr_shot"), ("video", "plates/shot.mov")])
        seq = routes.browse("plates/exr_shot")["items"]
        self.assertEqual([(i["kind"], i["frames"]) for i in seq], [("sequence", 3)])
        self.assertTrue(seq[0]["path"].startswith("plates/exr_shot/") and "#" in seq[0]["path"])
        out = routes.browse("output:")
        self.assertEqual(out["path"], "output:")
        kinds = {i["path"]: i["kind"] for i in out["items"]}
        self.assertEqual(kinds["output:video"], "folder")
        self.assertEqual(kinds["output:ComfyUI_#####_.png"], "sequence")  # core Save Image's names, one plate
        self.assertEqual(kinds["output:anim_00001_.webp"], "video")  # core Save Animated WEBP
        self.assertEqual(routes.browse("output:video")["parent"], "output:")
        for bad in ("../", "output:../", "plates/shot.mov", "/etc"):
            with self.assertRaises((FileNotFoundError, ValueError), msg=bad):
                routes.browse(bad)

    def test_a_root_lists_the_newest_plates_below_it(self):
        """At the input or output root, the plates of the folders below, newest first, each with its folder; PaintAPlate's
        own folders stay out. Inside a folder, only that folder."""
        import shutil
        import numpy as np, plateio
        renders = os.path.join(OUT, "paintaplate", "rootscan", "v1")
        os.makedirs(renders, exist_ok=True)
        try:
            plateio.write_movie(lambda i: np.zeros((32, 64, 3), np.uint8), 3, os.path.join(renders, "raw.mp4"), 24)
            found = {i["path"]: i["folder"] for i in routes.browse("")["found"]}
            self.assertEqual(found.get("plates/shot.mov"), "plates")
            self.assertTrue(any(p.startswith("plates/exr_shot/") and "#" in p for p in found), found)
            out = routes.browse("output:")["found"]
            paths = [i["path"] for i in out]
            self.assertIn("output:video/ComfyUI_00001_.mp4", paths)
            self.assertFalse([p for p in paths if p.startswith("output:paintaplate")], "renders stay out")
            self.assertNotIn("output:anim_00001_.webp", paths, "the root's own plates are its items, listed once")
            self.assertEqual([i["mtime"] for i in out], sorted((i["mtime"] for i in out), reverse=True))
            self.assertEqual(routes.browse("plates")["found"], [])
        finally:
            shutil.rmtree(os.path.join(OUT, "paintaplate", "rootscan"), ignore_errors=True)

    def test_the_version_is_pyproject_s(self):
        """The page's top bar and its log show the pack's version, read from pyproject.toml."""
        import json, tomllib
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            self.assertEqual(routes.VERSION, tomllib.load(f)["project"]["version"])
        self.assertEqual(json.loads(asyncio.run(routes.version_route(None)).text), {"version": routes.VERSION})

    def test_plate_info_names_the_colour_space_in_the_config(self):
        info = routes.plate_info("plates/exr_shot")
        self.assertEqual((info["kind"], info["frames"], info["color_space"]), ("sequence", 3, "ACEScg"))  # AP1 chromaticities
        info = routes.plate_info("plates/shot.mov")
        self.assertEqual((info["kind"], info["width"], info["color_space"]), ("video", 96, "sRGB Encoded Rec.709 (sRGB)"))
        self.assertEqual(routes.plate_info("output:ComfyUI_#####_.png")["frames"], 3)

    def test_scenes_saved_on_this_comfyui(self):
        import json
        scene = {"format": "paintaplate-scene", "plate": {"path": "plates/shot.mov"}, "edits": [{}, {}]}
        routes.save_scene("shot010", json.dumps(scene).encode())
        self.assertEqual([(x["name"], x["plate"], x["edits"]) for x in routes.list_scenes()], [("shot010", "shot.mov", 2)])
        with open(routes.scene_path("shot010"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), scene)
        for bad in ("../x", ".hidden", "a/b", ""):
            with self.assertRaises(ValueError, msg=bad):
                routes.scene_path(bad)
        for body in (b'{"format": "something else"}', b"[]", b'"text"'):  # JSON that is no scene: refused, never a server error
            with self.assertRaises(ValueError, msg=body):
                routes.save_scene("other", body)
        target = os.path.join(OUT, "not_a_scene.txt")
        touch(target, b"private")
        os.symlink(target, routes.scene_path("linked"))  # a link is never followed
        with self.assertRaises(web.HTTPNotFound):
            asyncio.run(routes.scene_get(types.SimpleNamespace(match_info={"name": "linked"})))
        self.assertNotIn("linked", [x["name"] for x in routes.list_scenes()])

    def test_thumbnails_are_jpegs_made_once(self):
        from PIL import Image
        for rel in ("plates/shot.mov", "plates/exr_shot", "output:video/ComfyUI_00001_.mp4", "output:ComfyUI_#####_.png",
                    "output:anim_00001_.webp"):
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
                r = await client.get("/paintaplate/browse", params={"path": "plates"})
                self.assertEqual(r.status, 200)
                self.assertEqual(sorted(i["name"] for i in (await r.json())["items"]), ["empty_folder", "exr_shot", "shot.mov"])
                r = await client.get("/paintaplate/stat", params={"path": "plates/shot.mov"})
                self.assertEqual((await r.json())["frames"], 5)
                r = await client.get("/paintaplate/ocio")
                self.assertIn("sRGB - Display", [d["name"] for d in (await r.json())["displays"]])
                r = await client.get("/paintaplate/ocio/shader", params={"space": "ACEScg", "display": "sRGB - Display", "view": "Raw"})
                self.assertIn("ocioOut", (await r.json())["out"]["text"])
                r = await client.get("/paintaplate/ocio/shader", params={"space": "nothing", "display": "x", "view": "y"})
                self.assertEqual(r.status, 400)
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


class DeepFramesTest(unittest.TestCase):
    def test_frames_keep_values_above_white(self):
        import numpy as np
        import OpenEXR
        folder = os.path.join(INPUT, "deep_seq")
        os.makedirs(folder, exist_ok=True)
        for i in range(3):
            rgb = np.zeros((100, 200, 3), np.float16)
            rgb[..., 0], rgb[..., 1], rgb[..., 2] = 2.5 + i, 0.25, -0.125
            OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage},
                         {"RGB": rgb}).write(os.path.join(folder, f"f.{1001 + i}.exr"))
        body, w, h = routes.deep_frames("deep_seq", 1, 2, 80)
        self.assertEqual((w, h), (80, 40))
        data = np.frombuffer(body, "<f2").reshape(2, h, w, 3).astype(np.float32)
        np.testing.assert_allclose(data[:, 2:-2, 2:-2].mean((1, 2)), [[3.5, 0.25, -0.125], [4.5, 0.25, -0.125]], atol=0.01)
        body, w, h = routes.deep_frames("deep_seq", 2, 3, 256)  # past the end, the last frame holds
        self.assertEqual(len(body), 3 * 100 * 200 * 3 * 2)
        with self.assertRaises(ValueError):
            routes.deep_frames("../outside", 0, 1, 64)
        export = os.path.join(OUT, "paintaplate", "deep", "v1", "export")  # an EXR export, as Save Plate writes it
        os.makedirs(export, exist_ok=True)
        OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage},
                     {"RGB": np.full((10, 20, 3), 6.0, np.float16)}).write(os.path.join(export, "f.1001.exr"))
        body, w, h = routes.deep_frames("output:paintaplate/deep/v1/export", 0, 1, 256)
        self.assertEqual((w, h, float(np.frombuffer(body, "<f2")[0])), (20, 10, 6.0))
        with self.assertRaises(ValueError):
            routes.deep_frames("output:../escape", 0, 1, 64)
        review = os.path.join(OUT, "paintaplate", "deep", "v1", "review")  # the review frames Save Frames writes in EXR
        os.makedirs(review, exist_ok=True)
        import plateio
        plateio.write_exrs(lambda i: np.full((10, 20, 3), 3.0 + i, np.float32), [os.path.join(review, f"frames_{k:05d}_.exr") for k in (1, 2)])
        body, w, h = routes.deep_frames("output:paintaplate/deep/v1/review/frames_#####_.exr", 1, 1, 256)
        self.assertEqual(float(np.frombuffer(body, "<f2")[0]), 4.0)
        print("deep frames: ok (values above 1.0 and below 0 kept as half floats, resized, held past the end)")

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

        async def malformed():
            return {"outputs": {"1": {"images": 5}}}
        resp = asyncio.run(routes.job_post(types.SimpleNamespace(match_info={"key": "b" * 40}, json=malformed)))
        self.assertEqual(resp.status, 400)  # a malformed record is refused, never a server error

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
            with self.assertRaises((FileNotFoundError, ValueError), msg=bad):
                routes.plate_stat(bad)
