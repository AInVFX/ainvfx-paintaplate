"""A plate from any path on the machine: an absolute path names a movie, a frame of a sequence (the whole sequence) or a
folder. Only a plate's extension is read; Windows' forms name nothing on another system; each refusal says why in one
sentence. The Open dialog lists such a folder's subfolders and plates by their absolute paths."""
import os
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import test_routes  # noqa: E402  the stand-ins for ComfyUI's folders, shared with the route tests

routes = test_routes.routes
folders, plateio = routes.folders, routes.plateio


class AbsolutePaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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

    def test_page_paths_still_stay_inside_comfyuis_folders(self):
        with self.assertRaises(ValueError):
            folders.plate_path("../outside.mov")
        with self.assertRaises(ValueError):
            folders.plate_path("output:" + self.d)


if __name__ == "__main__":
    unittest.main()
