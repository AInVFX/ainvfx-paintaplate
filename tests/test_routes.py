"""The download route: which folders it reads, what each zip holds, and that it stays inside output/paintaplate."""
import asyncio
import logging
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
                         "/paintaplate/frames", "/paintaplate/pixel", "/paintaplate/scenes", "/paintaplate/scenes/{name}", "/paintaplate/scenes/{name}",
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

    def test_a_thumbnail_of_files_named_by_the_millisecond(self):
        """ComfyUI's clipspace files in the input folder: the Open dialog lists them as one pattern, the plate has as many
        frames as files, and its thumbnail is the first file's picture. On 11 Nov this request took ComfyUI's memory."""
        import numpy as np
        from PIL import Image
        stamps = (1791816680123, 1791819680130, 1791821680123)
        paths = [os.path.join(INPUT, f"clipspace-mask-{n}.png") for n in stamps]
        for k, path in enumerate(paths):
            Image.new("RGB", (96, 48), (220, 0, 0) if k == 0 else (0, 0, 220)).save(path)
        try:
            item = next(i for i in routes.browse("")["items"] if i["name"].startswith("clipspace-mask-"))
            self.assertEqual(item["kind"], "sequence")
            self.assertEqual(routes.plate_info(item["path"])["frames"], 3)
            thumb = np.asarray(Image.open(routes.thumbnail(item["path"])).convert("RGB"), np.float32)
            self.assertGreater(thumb[..., 0].mean(), 150)
            self.assertLess(thumb[..., 2].mean(), 60)
        finally:
            for path in paths:
                os.remove(path)

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
        """At the input or output root, the plates of the folders below, newest first, each with its folder; Paint a plate's
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
        self.assertEqual(json.loads(asyncio.run(routes.version_route(None)).text), {"version": routes.VERSION, "build": routes.BUILD})

    def test_plate_info_names_the_colour_space_in_the_config(self):
        info = routes.plate_info("plates/exr_shot")
        self.assertEqual((info["kind"], info["frames"], info["color_space"]), ("sequence", 3, "ACEScg"))  # AP1 chromaticities
        info = routes.plate_info("plates/shot.mov")
        self.assertEqual((info["kind"], info["width"], info["color_space"]), ("video", 96, "sRGB Encoded Rec.709 (sRGB)"))
        self.assertEqual(routes.plate_info("output:ComfyUI_#####_.png")["frames"], 3)
        # headroom: what code value 1.0 decodes to in scene-linear; above 1.0 a log encoding holds SDR to HDR's values
        self.assertEqual(routes.plate_info("plates/shot.mov")["headroom"], 1.0)
        self.assertGreater(routes.plate_info("plates/shot.mov", cs="ACEScct")["headroom"], 200)

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



class Build(unittest.TestCase):
    """/paintaplate/version's build (render workstream): a hash of what computes, made when ComfyUI starts. The page puts it
    in every job index key in place of the version (comfy.indexParts)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="paintaplate_build_")
        self.pack, self.comfy, self.ltx = (os.path.join(self.dir, n) for n in ("pack", "ComfyUI", "ComfyUI-LTXVideo"))
        touch(os.path.join(self.pack, "nodes.py"), b"STRENGTH = 1\n")
        touch(os.path.join(self.pack, "pyproject.toml"), b'version = "1.11.12"\n')
        touch(os.path.join(self.pack, "tests", "test_nodes.py"), b"")
        touch(os.path.join(self.comfy, "comfyui_version.py"), b'__version__ = "0.42.1"\n')
        touch(os.path.join(self.ltx, ".git", "HEAD"), b"ref: refs/heads/master\n")
        touch(os.path.join(self.ltx, ".git", "refs", "heads", "master"), b"a" * 40 + b"\n")
        touch(os.path.join(self.dir, "models", "ltx.safetensors"), b"weights")

    def build(self):
        find = lambda name: os.path.join(self.dir, "models", name)  # noqa: E731
        stats = routes.model_stats(["ltx.safetensors", "hdr.safetensors"], find)
        return routes.build_hash(routes.build_parts(self.pack, self.comfy, self.ltx, stats))

    def test_the_build_is_16_hex_digits_made_at_start(self):
        self.assertRegex(routes.BUILD, r"^[0-9a-f]{16}$")
        self.assertEqual(routes.build_hash(routes.build_parts()), routes.BUILD, "the same code and files as at start")

    def test_what_computes_makes_another_build(self):
        builds = [self.build()]
        self.assertEqual(self.build(), builds[0], "the same code and the same files: the same build")
        changes = [  # each one alone makes a build no index has seen
            lambda: touch(os.path.join(self.pack, "nodes.py"), b"STRENGTH = 2\n"),  # a branch or a local edit of one version
            lambda: touch(os.path.join(self.pack, "plateio.py"), b""),  # a new Python file
            lambda: touch(os.path.join(self.comfy, "comfyui_version.py"), b'__version__ = "0.43.0"\n'),
            lambda: touch(os.path.join(self.ltx, ".git", "refs", "heads", "master"), b"b" * 40 + b"\n"),
            lambda: touch(os.path.join(self.dir, "models", "ltx.safetensors"), b"other weights"),  # a new file, an old name
            lambda: os.utime(os.path.join(self.dir, "models", "ltx.safetensors"), (1e9, 1e9)),  # the same size, another time
            lambda: touch(os.path.join(self.dir, "models", "hdr.safetensors"), b"hdr"),  # a model file that was missing
        ]
        for change in changes:
            change()
            builds.append(self.build())
        self.assertEqual(len(set(builds)), len(builds), builds)

    def test_what_does_not_compute_leaves_it(self):
        before = self.build()
        touch(os.path.join(self.pack, "pyproject.toml"), b'version = "1.11.13"\n')  # a new version number alone
        touch(os.path.join(self.pack, "tests", "test_nodes.py"), b"# a new test\n")  # tests do not run in ComfyUI
        touch(os.path.join(self.pack, "web", "app.mjs"), b"")  # the page: its workflows and values are in each key already
        self.assertEqual(self.build(), before)

    def test_a_clone_s_commit_is_read_from_its_git_folder(self):
        sha = "c" * 40
        touch(os.path.join(self.dir, "packed", ".git", "HEAD"), b"ref: refs/heads/main\n")
        touch(os.path.join(self.dir, "packed", ".git", "packed-refs"), f"# pack-refs\n{sha} refs/heads/main\n".encode())
        touch(os.path.join(self.dir, "detached", ".git", "HEAD"), f"{sha}\n".encode())
        commits = [routes.git_commit(os.path.join(self.dir, n)) for n in ("ComfyUI-LTXVideo", "packed", "detached", "pack")]
        self.assertEqual(commits, ["a" * 40, sha, sha, ""])

    def test_ltx_without_git_counts_by_its_python_files(self):
        import shutil
        shutil.rmtree(os.path.join(self.ltx, ".git"))
        touch(os.path.join(self.ltx, "nodes", "guide.py"), b"A = 1\n")
        before = self.build()
        touch(os.path.join(self.ltx, "nodes", "guide.py"), b"A = 2\n")
        self.assertNotEqual(self.build(), before, "installed from a zip: a change in any of its Python files makes another build")

    def test_a_model_file_is_found_in_any_model_folder(self):
        from unittest import mock
        folders = {"loras": [os.path.join(self.dir, "loras")], "vae": [os.path.join(self.dir, "models")]}
        full = lambda kind, name: next((os.path.join(p, name) for p in folders[kind] if os.path.isfile(os.path.join(p, name))), None)  # noqa: E731
        with mock.patch.object(routes, "folder_paths", types.SimpleNamespace(folder_names_and_paths=folders, get_full_path=full)):
            self.assertEqual(routes.model_path("ltx.safetensors"), os.path.join(self.dir, "models", "ltx.safetensors"))
            self.assertIsNone(routes.model_path("hdr.safetensors"))


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


class FluidExport(unittest.TestCase):
    def test_a_fluid_shot_zips_its_hdr_frames_its_plate_and_its_preview(self):
        """A fluid shot exported by itself: the zip holds its HDR frames and its shot as folders, and its preview movie."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for rel in ("hdr/f_00001_.exr", "hdr/f_00002_.exr", "plate/blank_960x512.mov", "preview_00001_.mp4", "hdr_movie_00001_.mp4"):
                os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(d, rel), "wb") as f:
                    f.write(b"x")
            names = [name for _, name in routes.collect(d, ["hdr", "plate", "preview"])]
            self.assertEqual(names, ["hdr/f_00001_.exr", "hdr/f_00002_.exr", "plate/blank_960x512.mov", "preview.mp4"])
            import zipfile  # its zip needs no export folder (it answered 404 on 2 Nov, and the browser cancelled the download)
            with zipfile.ZipFile(routes.build_zip(d, "fluid_v1", ["hdr", "plate", "preview"])) as z:
                self.assertEqual(sorted(z.namelist()), sorted(names))
            with self.assertRaises(FileNotFoundError):
                routes.build_zip(d, "fluid_v1", ["export", "matte"])


class ModelsZipTest(unittest.TestCase):
    def test_models_md_lists_the_models_behind_an_export(self):
        """MODELS.md in an export's zip: the models the page names, with their licences from web/models.json."""
        text = routes.models_md(["klein", "ltx", "nothing-like-this"])
        self.assertIn("FLUX 3 Image Klein", text)
        self.assertIn("FLUX Kommunity License", text)
        self.assertNotIn("nothing-like-this", text)
        self.assertEqual(text.count("\n| "), 4, "a header row, its rule and two models")  # the table's lines
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "export"))
            open(os.path.join(d, "export", "plate.mp4"), "wb").write(b"0")
            path = routes.build_zip(d, "shot", ["export"], ["klein"])
            names = zipfile.ZipFile(path).namelist()
            self.assertIn("MODELS.md", names)
            self.assertNotEqual(path, routes.build_zip(d, "shot", ["export"], ["klein", "ltx"]), "another list, another zip")
        print("MODELS.md: the models behind an export with their licences, in its zip")


class TraceTest(unittest.TestCase):
    """PAINTAPLATE_TRACE=1: every request says when it starts and when it ends, with what the process holds."""

    def call(self, method, path_qs, seconds=0.0):
        async def handler(request):
            await asyncio.sleep(seconds)
            return "answer"
        request = types.SimpleNamespace(method=method, path_qs=path_qs, path=path_qs.split("?")[0])
        return asyncio.run(routes.trace(request, handler))

    def test_a_request_says_when_it_starts_and_when_it_ends(self):
        with self.assertLogs(level="INFO") as said:
            self.assertEqual(self.call("GET", "/paintaplate/thumb?path=plates/horse.mp4"), "answer")
        lines = [r.getMessage() for r in said.records]
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^Paint a plate trace: starts GET /paintaplate/thumb\?path=plates/horse\.mp4, at \d+\.\d GB$")
        self.assertRegex(lines[1], r"^Paint a plate trace: ends GET /paintaplate/thumb\?path=plates/horse\.mp4 after \d+\.\d\d s, at \d+\.\d GB$")

    def test_a_front_end_file_is_said_only_when_it_is_slow(self):
        with self.assertLogs(level="INFO") as said:
            logging.getLogger().info("so that assertLogs has a line")
            self.call("GET", "/extensions/ainvfx-paintaplate/app.mjs")
        self.assertEqual(len(said.records), 1)
        with self.assertLogs(level="INFO") as said:
            self.call("GET", "/extensions/ainvfx-paintaplate/app.mjs", seconds=0.6)
        self.assertIn("ends GET /extensions/ainvfx-paintaplate/app.mjs after 0.6", said.records[0].getMessage())

    def test_a_request_that_fails_still_says_that_it_ended(self):
        async def handler(request):
            raise web.HTTPNotFound(text="No thumbnail")
        request = types.SimpleNamespace(method="GET", path_qs="/paintaplate/thumb?path=x", path="/paintaplate/thumb")
        with self.assertLogs(level="INFO") as said, self.assertRaises(web.HTTPNotFound):
            asyncio.run(routes.trace(request, handler))
        self.assertIn("ends GET /paintaplate/thumb?path=x", said.records[-1].getMessage())
