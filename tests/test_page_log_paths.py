"""/paintaplate/version gives ComfyUI's folder, from which the log's export writes the paths it holds
(web/logic.mjs: plainPaths). A folder_paths without base_path gives none."""
import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from _env import ROOT, require
require("aiohttp")


class VersionFolder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "folder_paths" not in sys.modules:  # run alone: routes.py imports folder_paths, whose folders this test never reads
            out = tempfile.mkdtemp(prefix="paintaplate_out_")
            sys.modules["folder_paths"] = types.SimpleNamespace(get_output_directory=lambda: out, get_input_directory=lambda: out,
                                                                get_temp_directory=lambda: out)
        sys.path.insert(0, ROOT)
        import routes
        cls.routes = routes

    def answer(self, folder_paths):
        with mock.patch.object(self.routes, "folder_paths", folder_paths):
            return json.loads(asyncio.run(self.routes.version_route(None)).text)

    def test_the_folder_comes_with_the_version_and_the_build(self):
        folder = os.path.join(os.sep, "data", "ComfyUI")
        got = self.answer(types.SimpleNamespace(base_path=folder))
        self.assertEqual((sorted(got), got["folder"]), (["build", "folder", "version"], folder))

    def test_a_folder_paths_without_base_path_gives_none(self):
        self.assertEqual(self.answer(types.SimpleNamespace())["folder"], "")


if __name__ == "__main__":
    unittest.main()
