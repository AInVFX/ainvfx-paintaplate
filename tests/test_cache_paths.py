"""The unused cache and its route: an export is told from its path under output/paintaplate, and a malformed request
is refused."""
import asyncio
import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from test_routes import touch  # importing it installs its stand-in for ComfyUI's folder_paths, which routes imports
import cache
import routes


class CachePaths(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="paintaplate_cache_")
        self.addCleanup(shutil.rmtree, self.dir)

    def test_a_folder_named_export_above_comfyui_hides_no_unused_file(self):
        out = os.path.join(self.dir, "export", "ComfyUI", "output")  # ComfyUI itself sits under a folder named export
        old, kept = os.path.join(out, "paintaplate", "p1", "v1", "shot", "f_00001_.png"), os.path.join(out, "paintaplate", "p1", "v1", "export", "plate.mov")
        for path in (old, kept):
            touch(path)
        self.assertEqual([p for p, _ in cache.unused(out)], [old])  # the render's frames are unused; its export always stays
        self.assertTrue(cache.is_export(os.path.join("p1", "v1", "export_copy.mov")))  # a file whose name holds « export » stays too

    def test_the_route_refuses_a_body_that_is_no_object(self):
        async def a_list():
            return ["keep"]
        with mock.patch.object(routes.folder_paths, "get_output_directory", lambda: self.dir, create=True):
            resp = asyncio.run(routes.cache_route(types.SimpleNamespace(can_read_body=True, json=a_list)))
            self.assertEqual(resp.status, 400)
            async def an_object():
                return {"keep": ["paintaplate/p1/v1"], "clear": False}
            resp = asyncio.run(routes.cache_route(types.SimpleNamespace(can_read_body=True, json=an_object)))
            self.assertEqual((resp.status, json.loads(resp.text)), (200, {"files": 0, "bytes": 0, "cleared": False}))


if __name__ == "__main__":
    unittest.main()
