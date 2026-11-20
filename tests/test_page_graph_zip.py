"""Export's ComfyUI graph in its zip: POST /paintaplate/graph writes the page's graph into the run's folder as
scene.comfyui.json, and the zip takes the file. It refuses a folder outside output/paintaplate and a body that is not
JSON, is not a ComfyUI workflow or is larger than 16 MB, and it never writes through a symbolic link."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import zipfile

from _env import ROOT

sys.path.insert(0, ROOT)
from aiohttp import web  # noqa: E402


def load_routes():  # routes as another test module loaded it, with its folder_paths; else with a stub of our own
    if "routes" not in sys.modules:
        out, inp = tempfile.mkdtemp(), tempfile.mkdtemp()
        sys.modules.setdefault("folder_paths", types.SimpleNamespace(get_output_directory=lambda: out, get_input_directory=lambda: inp,
                                                                      get_temp_directory=lambda: out))
    import routes
    return routes


class Request:  # what graph_post reads of a request: its query and its body
    def __init__(self, query, body):
        self.query, self.body = query, body

    async def read(self):
        return self.body if isinstance(self.body, bytes) else self.body.encode()


class GraphInZip(unittest.TestCase):
    def setUp(self):
        global routes
        routes = load_routes()
        out = routes.folders.folder_paths.get_output_directory()  # the output folder that routes reads
        self.rel = f"paintaplate/graphtest{os.getpid()}/v1"
        self.folder = os.path.join(out, self.rel)
        os.makedirs(os.path.join(self.folder, "export"), exist_ok=True)
        open(os.path.join(self.folder, "export", "f_00001.png"), "wb").write(b"png")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.folder), True)  # the other tests of output/paintaplate find nothing of it

    def test_the_route_writes_the_graph_and_the_zip_takes_it(self):
        graph = {"nodes": [{"id": 1, "type": "LoadImage"}], "groups": []}
        answer = asyncio.run(routes.graph_post(Request({"run": self.rel}, json.dumps(graph))))
        self.assertEqual(json.loads(answer.body), {"file": "scene.comfyui.json"})
        with open(os.path.join(self.folder, "scene.comfyui.json")) as f:
            self.assertEqual(json.load(f), graph)
        self.assertIn("scene.comfyui.json", [name for _, name in routes.collect(self.folder, ["export", "graph"])])
        with zipfile.ZipFile(routes.build_zip(self.folder, "shot", ["export", "graph"])) as z:
            self.assertEqual(json.loads(z.read("scene.comfyui.json")), graph)

    def test_a_body_that_is_not_json_and_a_folder_outside_are_refused(self):
        with self.assertRaises(web.HTTPBadRequest):
            asyncio.run(routes.graph_post(Request({"run": self.rel}, "not json")))
        with self.assertRaises(web.HTTPNotFound):
            asyncio.run(routes.graph_post(Request({"run": "../elsewhere"}, "{}")))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "scene.comfyui.json")))

    def test_a_body_that_is_no_workflow_or_is_too_large_is_refused(self):
        for body in ("{}", "[]", '{"nodes": 3}', "7"):  # JSON, but not a workflow in the editor's format: no list of nodes
            with self.assertRaises(web.HTTPBadRequest, msg=body):
                asyncio.run(routes.graph_post(Request({"run": self.rel}, body)))
        large = b'{"nodes": [], "pad": "' + b"x" * routes.GRAPH_MAX + b'"}'
        with self.assertRaises(web.HTTPBadRequest) as refused:
            asyncio.run(routes.graph_post(Request({"run": self.rel}, large)))
        self.assertIn("larger than 16 MB", refused.exception.text)
        self.assertEqual(os.listdir(self.folder), ["export"])  # nothing written, and no part file left

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_link_of_the_graphs_name_is_replaced_not_written_through(self):
        outside = os.path.join(tempfile.mkdtemp(), "kept.txt")
        self.addCleanup(shutil.rmtree, os.path.dirname(outside), True)
        open(outside, "w").write("kept")
        try:
            os.symlink(outside, os.path.join(self.folder, "scene.comfyui.json"))
        except OSError:
            self.skipTest("this account cannot make symbolic links")
        asyncio.run(routes.graph_post(Request({"run": self.rel}, '{"nodes": []}')))
        self.assertEqual(open(outside).read(), "kept")  # the file behind the link is as it was
        self.assertFalse(os.path.islink(os.path.join(self.folder, "scene.comfyui.json")))
        with open(os.path.join(self.folder, "scene.comfyui.json")) as f:
            self.assertEqual(json.load(f), {"nodes": []})


if __name__ == "__main__":
    unittest.main()
