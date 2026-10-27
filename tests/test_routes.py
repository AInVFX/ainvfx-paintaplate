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
sys.modules["folder_paths"] = types.SimpleNamespace(get_output_directory=lambda: OUT)
sys.path.insert(0, ROOT)
import routes  # noqa: E402
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
        self.assertEqual([r.path for r in app.routes], ["/paintaplate/download"])
        print("download route: folders, parts, symlinks, zip reuse, handler: ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
