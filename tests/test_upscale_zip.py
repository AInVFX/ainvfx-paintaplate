"""The zip's part « upscaled » takes the upscaled set of the size asked for: Upscale's steps keep one per size under the run's
folder, and the zip names it upscaled/, as before. A folder outside the run gives no file, and a value that is not an
upscaled set's folder makes the route read no folder at all."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from _env import ROOT, require
require("aiohttp")

OUT = tempfile.mkdtemp(prefix="paintaplate_out_")
INPUT = tempfile.mkdtemp(prefix="paintaplate_in_")
TEMP = tempfile.mkdtemp(prefix="paintaplate_tmp_")
sys.path.insert(0, ROOT)
routes = None


def setUpModule():  # routes as another test file may have imported it, with its own stand-in for ComfyUI's module
    global routes
    if "folder_paths" not in sys.modules:  # run alone: ComfyUI's module stands in, as test_routes.py makes it
        sys.modules["folder_paths"] = types.SimpleNamespace(get_output_directory=lambda: OUT, get_input_directory=lambda: INPUT,
                                                            get_temp_directory=lambda: TEMP)
    import routes as module
    routes = module


def touch(root, rel):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


NAMES = {"export": "composite_full_size", "review": "composite_full_size", "matte": "matte", "shot": "shot_full_size", "graph": "comfyui_graph",
         "hdr": "hdr", "plate": "fluid_shot", "preview": "fluid_shot_preview",
         "up": {"export": "composite_upscaled", "matte": "matte_upscaled"}}  # the zip's names, as the page sends them (logic.zipNames)

class UpscaledPart(unittest.TestCase):
    def setUp(self):
        self.run = tempfile.mkdtemp()
        for rel in ("upscale/1600x880/out/export/f_00001_.png", "upscale/1600x880/out/matte/matte_00001_.png", "upscale/3840x2112/out/export/f_00001_.png",
                    "upscale/1600x880/w000/f_00001_.png", "upscaled/export/old_00001_.png"):
            touch(self.run, rel)

    def test_the_size_asked_for_is_named_upscaled(self):
        names = [arc for _, arc in routes.collect(self.run, ["upscaled"], "upscale/1600x880/out", stem="desk", names=NAMES)]
        self.assertEqual(names, [os.path.join("composite_upscaled", "desk_composite_upscaled_00001_.png"), os.path.join("matte_upscaled", "desk_matte_upscaled_00001_.png")])

    def test_with_no_size_the_runs_own_upscaled_folder(self):
        names = [arc for _, arc in routes.collect(self.run, ["upscaled"], stem="desk", names=NAMES)]
        self.assertEqual(names, [os.path.join("composite_upscaled", "desk_composite_upscaled_00001_.png")])

    def test_a_folder_outside_the_run_gives_no_file(self):
        self.assertEqual(routes.collect(self.run, ["upscaled"], "../" + os.path.basename(self.run) + "_x"), [])
        self.assertEqual(routes.collect(self.run, ["upscaled"], "/etc"), [])

    def test_a_value_in_another_form_reads_no_folder(self):
        read = []
        with mock.patch.object(routes.os, "walk", side_effect=lambda top, *a, **k: read.append(top) or iter(())):
            for value in ("/", "/etc", ".", "..", "export", "upscale/1600x880", "upscale/1600x880/out/..", "upscale/1600x880/out/../../.."):
                self.assertEqual(routes.collect(self.run, ["upscaled"], value), [], value)
        self.assertEqual(read, [])

    def test_each_size_has_its_own_zip(self):
        a = routes.build_zip(self.run, "r", ["upscaled"], None, "upscale/1600x880/out")
        b = routes.build_zip(self.run, "r", ["upscaled"], None, "upscale/3840x2112/out")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
