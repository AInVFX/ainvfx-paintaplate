"""A plate from any path on the machine: an absolute path names a movie, a frame of a sequence (the whole sequence) or a
folder. Only a plate's extension is read; Windows' forms name nothing on another system; each refusal says why in one
sentence. The Open dialog lists such a folder's subfolders and plates by their absolute paths. An absolute path opens only
when ComfyUI answers this machine alone: a listener on the network refuses it, and so does a route in a request that a
proxy passed on."""
import asyncio
import os
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import test_routes  # noqa: E402  the stand-ins for ComfyUI's folders, shared with the route tests

routes = test_routes.routes
folders, plateio = routes.folders, routes.plateio
HERE_ONLY = mock.patch.object(folders, "listens", lambda: ["127.0.0.1"])  # ComfyUI's default listener: this machine alone


class AbsolutePaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        HERE_ONLY.start()
        cls.addClassCleanup(HERE_ONLY.stop)
        cls.d = tempfile.mkdtemp(prefix="paintaplate_machine_")
        os.makedirs(os.path.join(cls.d, "seq")); os.makedirs(os.path.join(cls.d, "empty"))
        frame = np.full((16, 16, 3), 0.5, np.float32)
        plateio.write_exrs(lambda i: frame, [os.path.join(cls.d, "seq", f"plate.{1001 + i}.exr") for i in range(3)], workers=1, fps=24.0)
        for name in ("clip.mp4", "notes.txt", "locked.mov"):
            open(os.path.join(cls.d, name), "wb").write(b"\0")
        os.chmod(os.path.join(cls.d, "locked.mov"), 0)

    def test_a_folder_a_movie_and_a_pattern_resolve_as_named(self):
        for name in ("seq", "clip.mp4", os.path.join("seq", "plate.####.exr")):
            self.assertEqual(folders.plate_path(os.path.join(self.d, name)), os.path.join(self.d, name))

    def test_a_frame_of_a_sequence_names_the_whole_sequence(self):
        self.assertEqual(folders.plate_path(os.path.join(self.d, "seq", "plate.1002.exr")),
                         os.path.join(self.d, "seq", "plate.####.exr"))

    def test_a_file_that_is_not_a_plate_is_refused(self):
        with self.assertRaises(ValueError) as e:
            folders.plate_path(os.path.join(self.d, "notes.txt"))
        self.assertEqual(str(e.exception), "notes.txt is not a plate: open a movie, a frame of a sequence or a folder.")

    def test_nothing_there_and_windows_forms_here_name_nothing(self):
        for path in (os.path.join(self.d, "gone.mov"), "C:\\plates\\shot.mov", "C:/plates/shot.mov", "\\\\server\\share\\shot.mov"):
            self.assertTrue(folders.absolute(path), path)
            with self.assertRaises(FileNotFoundError) as e:
                folders.plate_path(path)
            self.assertEqual(str(e.exception), f"No file or folder at {path}.")

    @unittest.skipIf(os.geteuid() == 0, "root reads every file")
    def test_a_file_this_process_may_not_read_is_refused(self):
        path = os.path.join(self.d, "locked.mov")
        with self.assertRaises(PermissionError) as e:
            folders.plate_path(path)
        self.assertEqual(str(e.exception), f"ComfyUI cannot read {path}: check its permissions.")

    def test_browse_lists_subfolders_and_plates_by_absolute_path(self):
        listed = routes.browse(self.d)
        self.assertEqual((listed["path"], listed["parent"]), (self.d, os.path.dirname(self.d)))
        paths = {i["name"]: i["path"] for i in listed["items"]}
        self.assertNotIn("notes.txt", paths)
        self.assertEqual(paths["seq"], os.path.join(self.d, "seq"))
        self.assertEqual(paths["clip.mp4"], os.path.join(self.d, "clip.mp4"))
        seq = routes.browse(os.path.join(self.d, "seq"))["items"]
        self.assertEqual([i["path"] for i in seq], [os.path.join(self.d, "seq", "plate.####.exr")])

    def test_stat_says_a_folder_holds_no_plate(self):
        path = os.path.join(self.d, "empty")
        with self.assertRaises(FileNotFoundError) as e:
            routes.plate_info(path)
        self.assertEqual(str(e.exception), f"No plate in {path}.")

    def test_every_error_of_folders_ends_with_a_full_stop(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "folders.py")) as f:
            said = re.findall(r'raise \w+\(f?"(.*)"\)', f.read())
        self.assertGreaterEqual(len(said), 9)
        self.assertEqual([m for m in said if not m.endswith(".")], [])

    def test_page_paths_still_stay_inside_comfyuis_folders(self):
        with self.assertRaises(ValueError):
            folders.plate_path("../outside.mov")
        with self.assertRaises(ValueError):
            folders.plate_path("output:" + self.d)


class ThisMachineOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(prefix="paintaplate_listener_")
        cls.clip = os.path.join(cls.d, "clip.mp4")
        open(cls.clip, "wb").write(b"\0")
        test_routes.touch(os.path.join(test_routes.INPUT, "listener", "clip.mp4"))

    def test_a_listener_on_this_machine_alone_takes_an_absolute_path(self):
        for heard in (["127.0.0.1"], ["localhost"], ["::1"], ["127.0.0.1", "::1"], ["127.0.0.2"]):
            with mock.patch.object(folders, "listens", lambda heard=heard: heard):
                self.assertEqual(folders.plate_path(self.clip), self.clip, heard)

    def test_a_listener_on_the_network_refuses_it_and_says_what_to_do(self):
        for heard in (["0.0.0.0"], ["0.0.0.0", "::"], ["127.0.0.1", "192.168.1.20"], ["plates.example"], []):  # []: outside ComfyUI
            with mock.patch.object(folders, "listens", lambda heard=heard: heard):
                with self.assertRaises(PermissionError, msg=heard) as e:
                    folders.plate_path(self.clip)
                self.assertEqual(str(e.exception), "Full paths open only when ComfyUI runs on this machine. Upload the file instead.")
                self.assertTrue(folders.plate_path("listener/clip.mp4").endswith(os.path.join("listener", "clip.mp4")), "a page path opens on any listener")

    def test_a_route_refuses_an_absolute_path_that_a_proxy_passed_on(self):
        async def run():
            from aiohttp import web
            from aiohttp.test_utils import TestClient, TestServer
            table = web.RouteTableDef()
            routes.setup(types.SimpleNamespace(routes=table))
            app = web.Application()
            app.add_routes(table)
            async with TestClient(TestServer(app)) as client:
                for route, path in (("browse", self.d), ("stat", self.clip), ("thumb", self.clip), ("frames", self.clip), ("pixel", self.clip)):
                    for mark in ("X-Forwarded-For", "Forwarded"):
                        r = await client.get(f"/paintaplate/{route}", params={"path": path}, headers={mark: "203.0.113.7"})
                        self.assertEqual((r.status, await r.json()), (403, {"error": folders.THIS_MACHINE_ONLY}), f"{route}, {mark}")
                r = await client.get("/paintaplate/browse", params={"path": self.d})
                self.assertEqual((r.status, [i["name"] for i in (await r.json())["items"]]), (200, ["clip.mp4"]))
                r = await client.get("/paintaplate/browse", params={"path": "listener"}, headers={"X-Forwarded-For": "203.0.113.7"})
                self.assertEqual(r.status, 200, "a page path passes through a proxy, as before")
                with mock.patch.object(folders, "listens", lambda: ["0.0.0.0"]):
                    r = await client.get("/paintaplate/stat", params={"path": self.clip})
                    self.assertEqual((r.status, await r.json()), (403, {"error": folders.THIS_MACHINE_ONLY}))
        with HERE_ONLY:
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
