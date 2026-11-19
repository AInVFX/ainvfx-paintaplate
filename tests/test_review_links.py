"""Symbolic links in ComfyUI's folders: what the cache, the scenes list and a page path do with one."""
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from test_routes import touch  # importing it installs its stand-in for ComfyUI's folder_paths, which routes imports
import cache
import folders
import routes


class Links(unittest.TestCase):
    """Each test has its own input and output folders. The input folder is itself a link, as when it sits on another disk."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="paintaplate_links_")
        self.addCleanup(shutil.rmtree, self.dir)
        self.input, self.output, self.outside = (os.path.join(self.dir, n) for n in ("input", "output", "outside"))
        os.makedirs(os.path.join(self.dir, "disk", "input"))
        os.symlink(os.path.join(self.dir, "disk", "input"), self.input)
        os.makedirs(self.output)
        touch(os.path.join(self.outside, "keep.mov"))
        touch(os.path.join(self.outside, "v1", "frame.exr"))
        paths = types.SimpleNamespace(get_input_directory=lambda: self.input, get_output_directory=lambda: self.output,
                                      get_temp_directory=lambda: os.path.join(self.dir, "temp"))
        for module in (folders, routes):
            patcher = mock.patch.object(module, "folder_paths", paths)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_clearing_the_cache_never_follows_a_link_nor_removes_one(self):
        plate = os.path.join(self.output, "paintaplate", "plateA")
        touch(os.path.join(plate, "v1", "clean_00001_.mp4"))
        links = {os.path.join(plate, "v2"): self.outside,  # a render folder on another disk
                 os.path.join(plate, "v1", "frame.exr"): os.path.join(self.outside, "keep.mov"),  # one file of a render
                 os.path.join(plate, "proxy.mp4"): os.path.join(self.dir, "nowhere"),  # a link that leads nowhere
                 os.path.join(self.output, "paintaplate", "plateB"): self.outside}  # a plate's folder on another disk
        for link, target in links.items():
            os.symlink(target, link)
        self.assertEqual(cache.unused(self.output), [(os.path.join(plate, "v1", "clean_00001_.mp4"), 1)])
        self.assertEqual(cache.clear(self.output), (1, 1))
        self.assertTrue(all(os.path.islink(link) for link in links))
        self.assertTrue(os.path.isfile(os.path.join(self.outside, "keep.mov")) and os.path.isfile(os.path.join(self.outside, "v1", "frame.exr")))
