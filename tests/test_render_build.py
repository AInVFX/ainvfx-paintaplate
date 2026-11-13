"""The build line that routes.py writes when ComfyUI starts (render workstream, wave 7, R16): ComfyUI-LTXVideo's figure says
whether it is a commit or the hash of its Python files. The job index key (build_parts) keeps its value as it is."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_routes  # noqa: E402  its stubs let routes import without ComfyUI

routes = test_routes.routes


class LtxLabel(unittest.TestCase):
    def setUp(self):
        self.ltx = os.path.join(tempfile.mkdtemp(prefix="paintaplate_ltx_"), "ComfyUI-LTXVideo")
        test_routes.touch(os.path.join(self.ltx, "nodes.py"), b"A = 1\n")
        test_routes.touch(os.path.join(self.ltx, "pyproject.toml"), b'[project]\nname = "comfyui-ltxvideo"\nversion = "1.2.3"\n')

    def test_a_folder_that_is_not_a_git_clone_says_so_with_its_version(self):
        files = routes.python_digest(self.ltx, deep=True)
        self.assertEqual(routes.build_parts(self.ltx, "", self.ltx, [])["ltx"], files, "the key keeps the hash of the files")
        self.assertEqual(routes.ltx_label(self.ltx, files), f"1.2.3, files {files[:7]} (not a git clone)")
        os.remove(os.path.join(self.ltx, "pyproject.toml"))
        self.assertEqual(routes.ltx_label(self.ltx, files), f"files {files[:7]} (not a git clone)", "no version: the files alone")

    def test_a_git_clone_gives_its_commit(self):
        test_routes.touch(os.path.join(self.ltx, ".git", "HEAD"), b"ref: refs/heads/master\n")
        test_routes.touch(os.path.join(self.ltx, ".git", "refs", "heads", "master"), b"220e1d4" + b"0" * 33 + b"\n")
        commit = routes.build_parts(self.ltx, "", self.ltx, [])["ltx"]
        self.assertEqual(commit, "220e1d4" + "0" * 33, "the key keeps the commit")
        self.assertEqual(routes.ltx_label(self.ltx, commit), "220e1d4")

    def test_no_folder_reads_not_found(self):
        self.assertEqual(routes.ltx_label("", ""), "not found")


if __name__ == "__main__":
    unittest.main()
