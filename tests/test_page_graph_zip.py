"""Export's ComfyUI graphs in its zip: POST /paintaplate/graph writes each of the page's graphs into the run's folder as
<name>.comfyui.json, named after what it makes, and the zip takes each file. It refuses a name that is not a to z and « _ »,
a folder outside output/paintaplate and a body that is not JSON, is not a ComfyUI workflow or is larger than 16 MB, and it
never writes through a symbolic link."""
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
        answer = asyncio.run(routes.graph_post(Request({"run": self.rel, "name": "edits"}, json.dumps(graph))))
        self.assertEqual(json.loads(answer.body), {"file": "edits.comfyui.json"})
        with open(os.path.join(self.folder, "edits.comfyui.json")) as f:
            self.assertEqual(json.load(f), graph)
        files = routes.zip_entries([("composite_full_size", f"output:{self.rel}/export"), ("comfyui_graph", f"output:{self.rel}/edits.comfyui.json")], "desk")
        self.assertIn("desk_comfyui_graph.json", [name for _, name, _ in files])
        with zipfile.ZipFile(routes.build_zip(self.folder, "shot", files, None, "desk")) as z:
            self.assertEqual(json.loads(z.read("desk_comfyui_graph.json")), graph)

    def test_two_graphs_side_by_side_each_named_after_what_it_makes(self):
        made = {"fluid_shot": {"nodes": [{"id": 1, "type": "PaintAPlate_KeyframeVideo"}]}, "edits": {"nodes": [{"id": 1, "type": "LoadImage"}]}}
        for name, graph in made.items():
            answer = asyncio.run(routes.graph_post(Request({"run": self.rel, "name": name}, json.dumps(graph))))
            self.assertEqual(json.loads(answer.body), {"file": f"{name}.comfyui.json"})
        rows = [(f"{name}_comfyui_graph", f"output:{self.rel}/{name}.comfyui.json") for name in made]
        files = routes.zip_entries(rows, "desk")
        self.assertEqual([arc for _, arc, _ in files], ["desk_fluid_shot_comfyui_graph.json", "desk_edits_comfyui_graph.json"])
        with zipfile.ZipFile(routes.build_zip(self.folder, "shot", files, None, "desk")) as z:
            self.assertEqual({n: json.loads(z.read(f"desk_{n}_comfyui_graph.json")) for n in made}, made)

    def test_a_name_that_is_not_a_to_z_is_refused(self):
        for name in ("", "Edits", "../edits", "edits.json", "a" * 41):
            with self.assertRaises(web.HTTPBadRequest, msg=name):
                asyncio.run(routes.graph_post(Request({"run": self.rel, "name": name}, '{"nodes": []}')))
        self.assertEqual(os.listdir(self.folder), ["export"])

    def test_a_body_that_is_not_json_and_a_folder_outside_are_refused(self):
        with self.assertRaises(web.HTTPBadRequest):
            asyncio.run(routes.graph_post(Request({"run": self.rel, "name": "edits"}, "not json")))
        with self.assertRaises(web.HTTPNotFound):
            asyncio.run(routes.graph_post(Request({"run": "../elsewhere", "name": "edits"}, "{}")))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "edits.comfyui.json")))

    def test_a_body_that_is_no_workflow_or_is_too_large_is_refused(self):
        for body in ("{}", "[]", '{"nodes": 3}', "7"):  # JSON, but not a workflow in the editor's format: no list of nodes
            with self.assertRaises(web.HTTPBadRequest, msg=body):
                asyncio.run(routes.graph_post(Request({"run": self.rel, "name": "edits"}, body)))
        large = b'{"nodes": [], "pad": "' + b"x" * routes.GRAPH_MAX + b'"}'
        with self.assertRaises(web.HTTPBadRequest) as refused:
            asyncio.run(routes.graph_post(Request({"run": self.rel, "name": "edits"}, large)))
        self.assertIn("larger than 16 MB", refused.exception.text)
        self.assertEqual(os.listdir(self.folder), ["export"])  # nothing written, and no part file left

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_link_of_the_graphs_name_is_replaced_not_written_through(self):
        outside = os.path.join(tempfile.mkdtemp(), "kept.txt")
        self.addCleanup(shutil.rmtree, os.path.dirname(outside), True)
        open(outside, "w").write("kept")
        try:
            os.symlink(outside, os.path.join(self.folder, "edits.comfyui.json"))
        except OSError:
            self.skipTest("this account cannot make symbolic links")
        asyncio.run(routes.graph_post(Request({"run": self.rel, "name": "edits"}, '{"nodes": []}')))
        self.assertEqual(open(outside).read(), "kept")  # the file behind the link is as it was
        self.assertFalse(os.path.islink(os.path.join(self.folder, "edits.comfyui.json")))
        with open(os.path.join(self.folder, "edits.comfyui.json")) as f:
            self.assertEqual(json.load(f), {"nodes": []})



class GraphImagesInZip(unittest.TestCase):
    """The zip holds every image the graph's nodes load, from the top of ComfyUI's input folder, in input/ under the names
    the graph uses; a name with a folder in it, or a file that is not there, adds nothing."""

    def test_the_images_the_graph_loads_come_in_input(self):
        routes = load_routes()
        run = os.path.join(routes.folders.folder_paths.get_output_directory(), f"paintaplate/graphimages{os.getpid()}/v1")
        os.makedirs(run, exist_ok=True)
        self.addCleanup(shutil.rmtree, os.path.dirname(run), True)
        inputs = routes.folders.folder_paths.get_input_directory()
        for name in ("desk_e1_mask_0676e451.png", "desk_e1_strokes_7bcde075.png", "desk_e1_keyframe_12345678.png"):
            with open(os.path.join(inputs, name), "wb") as f:
                f.write(b"png")
            self.addCleanup(os.remove, os.path.join(inputs, name))
        nodes = [{"type": "LoadImageMask", "widgets_values": ["desk_e1_mask_0676e451.png", "red", "image"]},
                 {"type": "LoadImage", "widgets_values": ["desk_e1_strokes_7bcde075.png", "image"]},
                 {"type": "LoadImage", "widgets_values": ["../secret.png", "image"]}, {"type": "LoadImage", "widgets_values": ["gone.png", "image"]},
                 {"type": "MarkdownNote", "widgets_values": ["text"]},
                 {"type": "PaintAPlate_KeyframeVideo", "widgets_values": [960, 512, 17, json.dumps([{"frame": 0, "image": "desk_e1_keyframe_12345678.png"}])]}]
        with open(os.path.join(run, "edits.comfyui.json"), "w") as f:
            json.dump({"nodes": nodes}, f)
        got = [arc for _, arc, _ in routes.zip_entries([("comfyui_graph", f"output:paintaplate/graphimages{os.getpid()}/v1/edits.comfyui.json")], "desk")]
        self.assertEqual(got, ["desk_comfyui_graph.json", "input/desk_e1_mask_0676e451.png", "input/desk_e1_strokes_7bcde075.png",
                               "input/desk_e1_keyframe_12345678.png"])
        print("The zip holds the graph and its source images, in input/")


if __name__ == "__main__":
    unittest.main()
