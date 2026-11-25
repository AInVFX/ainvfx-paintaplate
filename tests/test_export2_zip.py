"""Export's zip takes the files the page names, row by row (routes.zip_list, row_files, zip_entries): each path is checked
as a plate's path is (folders.plate_path), under output/paintaplate only, and a row whose files are not on disk stops the
download, which the check route names first. A row can come from another render's folder: a step reused from it."""
import asyncio
import io
import json
import os
import shutil
import sys
import time
import unittest
import zipfile

from _env import ROOT

sys.path.insert(0, ROOT)
from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from test_export_source import load_routes, write  # noqa: E402


class ZipRows(unittest.TestCase):
    def setUp(self):
        self.routes = r = load_routes()
        self.out, self.inp = r.folders.folder_paths.get_output_directory(), r.folders.folder_paths.get_input_directory()
        self.top = f"paintaplate/ziptest{os.getpid()}"
        self.addCleanup(shutil.rmtree, os.path.join(self.out, self.top), True)
        self.v2, self.v3 = f"{self.top}/v2", f"{self.top}/v3"
        at = lambda rel: os.path.join(self.out, rel)  # noqa: E731
        write(at(f"{self.v3}/export/desk.mov"), b"c" * 10)
        for i in (1, 2, 3):
            write(at(f"{self.v3}/matte/matte_{i:05}_.png"), b"m")
        write(at(f"{self.v3}/matte/matte_00004_.png.part"), b"x")  # a file of another type in a row's folder stays out
        write(at(f"{self.v2}/full/raw_00001_.mp4"), b"s" * 10)  # the shot: render v3 took it from render v2
        for i in (1, 2):
            write(at(f"{self.v3}/hdr/f_{i:05}_.exr"), b"h")
        write(at(f"{self.top}/jobs.json"), b"{}")

    def rows(self, *pairs):
        return [(n, f"output:{p}") for n, p in pairs]

    def test_the_list_is_names_and_paths(self):
        z = self.routes.zip_list
        self.assertEqual(z(json.dumps([["matte", "output:a/matte"]])), [("matte", "output:a/matte")])
        for bad in ("not json", json.dumps({"matte": "x"}), json.dumps([["Matte", "x"]]), json.dumps([["matte", "x"], ["matte", "y"]]),
                    json.dumps([["m", 1]]), json.dumps([[f"r{i}", "x"] for i in range(self.routes.ZIP_ROWS + 1)])):
            with self.assertRaises(ValueError, msg=bad):
                z(bad)

    def test_a_row_is_a_movie_a_folder_or_a_frame_pattern(self):
        f = self.routes.row_files
        self.assertEqual([os.path.basename(p) for p in f(f"output:{self.v3}/export/desk.mov")], ["desk.mov"])
        self.assertEqual([os.path.basename(p) for p in f(f"output:{self.v3}/matte")], [f"matte_{i:05}_.png" for i in (1, 2, 3)])
        self.assertEqual([os.path.basename(p) for p in f(f"output:{self.v3}/hdr/f_#####_.exr")], ["f_00001_.exr", "f_00002_.exr"])
        write(os.path.join(self.out, self.v3, "hdr", "upscale", "3840x2160", "out", "comp", "f_00001_.exr"), b"u")  # Upscale's set of SDR to HDR's set
        self.assertEqual([os.path.basename(p) for p in f(f"output:{self.v3}/hdr/upscale/3840x2160/out/comp")], ["f_00001_.exr"])

    def test_paths_outside_output_paintaplate_links_and_other_types_are_refused(self):
        f = self.routes.row_files
        write(os.path.join(self.out, f"elsewhere{os.getpid()}.mp4"), b"x")
        self.addCleanup(os.remove, os.path.join(self.out, f"elsewhere{os.getpid()}.mp4"))
        link = os.path.join(self.out, self.v3, "linked.mov")
        os.symlink(os.path.join(self.out, self.v3, "export", "desk.mov"), link)
        for rel in (f"output:elsewhere{os.getpid()}.mp4", "output:../../etc", f"output:{self.v3}/linked.mov",
                    f"output:{self.top}/jobs.json", "plates/desk.mp4"):
            with self.assertRaises((ValueError, PermissionError), msg=rel):
                f(rel)
        with self.assertRaises(FileNotFoundError):
            f(f"output:{self.v3}/layer")

    def test_names_start_with_the_stem_then_the_row(self):
        files = self.routes.zip_entries(self.rows(("composite_full_size", f"{self.v3}/export"), ("matte", f"{self.v3}/matte"),
                                                  ("shot_full_size", f"{self.v2}/full/raw_00001_.mp4"), ("hdr", f"{self.v3}/hdr/f_#####_.exr")), "desk")
        self.assertEqual([a for _, a, _ in files], ["desk_composite_full_size.mov", "matte/desk_matte_00001_.png", "matte/desk_matte_00002_.png",
                                                    "matte/desk_matte_00003_.png", "desk_shot_full_size.mp4", "hdr/desk_hdr_00001_.exr", "hdr/desk_hdr_00002_.exr"])

    def test_every_row_without_a_file_is_named(self):
        with self.assertRaises(FileNotFoundError) as caught:
            self.routes.zip_entries(self.rows(("matte", f"{self.v3}/matte"), ("layer", f"{self.v3}/layer"), ("shot_full_size", f"{self.v3}/full/raw_00001_.mp4")), "desk")
        self.assertIn("layer, shot_full_size", str(caught.exception))
        self.assertEqual(self.routes.missing_rows(self.rows(("matte", f"{self.v3}/matte"), ("layer", f"{self.v3}/layer"))), ["layer"])

    def test_the_graph_comes_with_the_images_it_loads(self):
        write(os.path.join(self.out, self.v3, self.routes.GRAPH), json.dumps({"nodes": [{"type": "LoadImage", "widgets_values": [f"zt{os.getpid()}.png"]}]}).encode())
        write(os.path.join(self.inp, f"zt{os.getpid()}.png"), b"p")
        self.addCleanup(os.remove, os.path.join(self.inp, f"zt{os.getpid()}.png"))
        files = self.routes.zip_entries(self.rows(("comfyui_graph", f"{self.v3}/{self.routes.GRAPH}")), "desk")
        self.assertEqual([a for _, a, _ in files], ["desk_comfyui_graph.json", f"input/zt{os.getpid()}.png"])

    def test_a_zip_is_built_once_then_again_when_a_file_changes(self):
        run = os.path.join(self.out, self.v3)
        files = self.routes.zip_entries(self.rows(("matte", f"{self.v3}/matte")), "desk")
        first = self.routes.build_zip(run, "desk_v3", files, None, "desk")
        self.assertEqual(self.routes.build_zip(run, "desk_v3", files, None, "desk"), first)
        mtime = os.path.getmtime(first)
        time.sleep(0.05)
        write(os.path.join(run, "matte", "matte_00002_.png"), b"n")
        os.utime(first, (mtime - 10, mtime - 10))
        again = self.routes.build_zip(run, "desk_v3", files, None, "desk")
        self.assertEqual(again, first)
        self.assertGreater(os.path.getmtime(again), mtime - 10)
        other = self.routes.zip_entries(self.rows(("matte", f"{self.v3}/matte"), ("hdr", f"{self.v3}/hdr/f_#####_.exr")), "desk")
        self.assertNotEqual(self.routes.build_zip(run, "desk_v3", other, None, "desk"), first)

    def ask(self, route, params):
        async def go():
            app = web.Application()
            app.router.add_get("/paintaplate/download", self.routes.download)
            app.router.add_get("/paintaplate/download/check", self.routes.download_check)
            async with TestClient(TestServer(app)) as client:
                r = await client.get(route, params=params)
                return r.status, await r.read()
        return asyncio.run(go())

    def test_a_shot_reused_from_another_render_reaches_the_zip(self):
        files = json.dumps([["composite_full_size", f"output:{self.v3}/export"], ["shot_full_size", f"output:{self.v2}/full/raw_00001_.mp4"]])
        status, body = self.ask("/paintaplate/download", {"run": self.v3, "name": "desk_v3", "stem": "desk", "files": files})
        self.assertEqual(status, 200, body)
        self.assertEqual(sorted(zipfile.ZipFile(io.BytesIO(body)).namelist()), ["desk_composite_full_size.mov", "desk_shot_full_size.mp4"])

    def test_the_check_names_the_rows_with_no_file_and_the_download_refuses_them(self):
        files = json.dumps([["matte", f"output:{self.v3}/matte"], ["layer", f"output:{self.v3}/layer"]])
        status, body = self.ask("/paintaplate/download/check", {"files": files})
        self.assertEqual((status, json.loads(body)), (200, {"missing": ["layer"]}))
        status, body = self.ask("/paintaplate/download", {"run": self.v3, "name": "desk_v3", "files": files})
        self.assertEqual(status, 404)
        self.assertIn(b"layer", body)
        status, _ = self.ask("/paintaplate/download/check", {"files": json.dumps([["x", "output:../../etc"]])})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
