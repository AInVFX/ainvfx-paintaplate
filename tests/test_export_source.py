"""Export's « Source plate » row: the zip route sends the plate's own files, a movie or each frame of a sequence, under their
own names in source_plate/, streamed as the zip downloads, with no copy of them on disk; a path that leaves ComfyUI's
folders is refused; the size route answers their bytes."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
import io

from _env import ROOT

sys.path.insert(0, ROOT)
from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402


def load_routes():  # routes as another test module loaded it, with its folder_paths; else with a stub of our own
    if "routes" not in sys.modules:
        out, inp = tempfile.mkdtemp(), tempfile.mkdtemp()
        sys.modules.setdefault("folder_paths", types.SimpleNamespace(get_output_directory=lambda: out, get_input_directory=lambda: inp,
                                                                      get_temp_directory=lambda: out))
    import routes
    return routes


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class SourcePlate(unittest.TestCase):
    def setUp(self):
        self.routes = routes = load_routes()
        out, inp = routes.folders.folder_paths.get_output_directory(), routes.folders.folder_paths.get_input_directory()
        self.rel = f"paintaplate/sourcetest{os.getpid()}/v1"
        self.run = os.path.join(out, self.rel)
        write(os.path.join(self.run, "export", "plate_00001_.mp4"))
        self.addCleanup(shutil.rmtree, os.path.dirname(self.run), True)
        self.plates = os.path.join(inp, f"sourcetest{os.getpid()}")
        self.addCleanup(shutil.rmtree, self.plates, True)
        write(os.path.join(self.plates, "desk.mp4"), b"m" * 1000)
        for n in (1001, 1002, 1003):
            write(os.path.join(self.plates, "room", f"room.{n}.exr"), b"e" * 10)

    def get(self, params):
        async def go():
            app = web.Application()
            app.router.add_get("/paintaplate/download", self.routes.download)
            app.router.add_get("/paintaplate/download/size", self.routes.this_machine(self.routes.download_size))
            async with TestClient(TestServer(app)) as client:
                r = await client.get(params.pop("route", "/paintaplate/download"), params=params)
                return r.status, await r.read()
        return asyncio.run(go())

    def test_a_movie_comes_under_its_own_name_and_no_zip_stays_on_disk(self):
        status, body = self.get({"run": self.rel, "name": "desk_v1", "stem": "desk", "files": json.dumps([["composite_full_size", f"output:{self.rel}/export/plate_00001_.mp4"]]),
                                 "source": "source_plate", "plate": f"sourcetest{os.getpid()}/desk.mp4"})
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertEqual(sorted(z.namelist()), ["desk_composite_full_size.mp4", "source_plate/desk.mp4"])
            self.assertEqual(z.read("source_plate/desk.mp4"), b"m" * 1000)
        self.assertEqual([f for f in os.listdir(self.run) if f.endswith((".zip", ".part"))], [])  # streamed: no copy on disk
        print("The source plate's movie comes in source_plate/, streamed, with no zip left on disk")

    def test_each_frame_of_a_folder_comes_once(self):
        status, body = self.get({"run": self.rel, "name": "room_v1", "stem": "room", "files": json.dumps([["composite_full_size", f"output:{self.rel}/export/plate_00001_.mp4"]]),
                                 "source": "source_plate", "plate": f"sourcetest{os.getpid()}/room"})
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertEqual([n for n in sorted(z.namelist()) if n.startswith("source_plate/")],
                             ["source_plate/room.1001.exr", "source_plate/room.1002.exr", "source_plate/room.1003.exr"])
        print("Each frame of the source plate comes once, under its own name")

    def test_a_path_that_leaves_comfyuis_folders_is_refused(self):
        status, _ = self.get({"run": self.rel, "name": "x", "files": json.dumps([["composite_full_size", f"output:{self.rel}/export/plate_00001_.mp4"]]), "plate": "../../etc"})
        self.assertEqual(status, 403)
        print("A source plate outside ComfyUI's folders is refused")

    def test_the_size_route_answers_the_plates_bytes(self):
        status, body = self.get({"route": "/paintaplate/download/size", "path": f"sourcetest{os.getpid()}/room"})
        self.assertEqual((status, body), (200, b'{"files": 3, "bytes": 30}'))
        print("The size route answers the source plate's bytes")


if __name__ == "__main__":
    unittest.main()
