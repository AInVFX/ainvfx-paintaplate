"""The zip's part « upscaled » takes the upscaled set of the size asked for: Upscale's steps keep one per size under the run's
folder, and the zip names it upscaled/, as before. A folder outside the run gives no file."""
import os
import sys
import tempfile
import types
import unittest

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


class UpscaledPart(unittest.TestCase):
    def setUp(self):
        self.run = tempfile.mkdtemp()
        for rel in ("upscale/1600x880/out/export/f_00001_.png", "upscale/1600x880/out/matte/matte_00001_.png", "upscale/3840x2112/out/export/f_00001_.png",
                    "upscale/1600x880/w000/f_00001_.png", "upscaled/export/old_00001_.png"):
            touch(self.run, rel)

    def test_the_size_asked_for_is_named_upscaled(self):
        names = [arc for _, arc in routes.collect(self.run, ["upscaled"], "upscale/1600x880/out")]
        self.assertEqual(names, [os.path.join("upscaled", "export", "f_00001_.png"), os.path.join("upscaled", "matte", "matte_00001_.png")])

    def test_with_no_size_the_runs_own_upscaled_folder(self):
        names = [arc for _, arc in routes.collect(self.run, ["upscaled"])]
        self.assertEqual(names, [os.path.join("upscaled", "export", "old_00001_.png")])

    def test_a_folder_outside_the_run_gives_no_file(self):
        self.assertEqual(routes.collect(self.run, ["upscaled"], "../" + os.path.basename(self.run) + "_x"), [])
        self.assertEqual(routes.collect(self.run, ["upscaled"], "/etc"), [])

    def test_each_size_has_its_own_zip(self):
        a = routes.build_zip(self.run, "r", ["upscaled"], None, "upscale/1600x880/out")
        b = routes.build_zip(self.run, "r", ["upscaled"], None, "upscale/3840x2112/out")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
