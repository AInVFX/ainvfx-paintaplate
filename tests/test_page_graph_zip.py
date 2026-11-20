"""Export's ComfyUI graph in its zip: POST /paintaplate/graph writes the page's graph into the run's folder as
scene.comfyui.json, refuses a body that is not JSON and a folder outside output/paintaplate, and the zip takes the file."""
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

    async def text(self):
        return self.body


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


if __name__ == "__main__":
    unittest.main()
