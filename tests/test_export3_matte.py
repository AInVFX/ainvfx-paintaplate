"""The upscaled matte's files (plateio.save_names, nodes.SaveFrames' first): a window job that runs again writes its matte
frames under the same names, numbered by their frame in the shot, so the folder still holds one frame per frame of the
shot. Numbered on from the files there, as Save Image numbers them, the second run would add its frames after them."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import plateio  # noqa: E402


def run_window(folder, first, n):
    """One run of a window's matte save: the names Save Frames gives, the counter after the files there, as ComfyUI counts."""
    counter = len(os.listdir(folder)) + 1
    for name in plateio.save_names("matte", counter, n, "png", first):
        open(os.path.join(folder, name), "w").close()


class MatteFrames(unittest.TestCase):
    def test_a_window_job_that_runs_again_keeps_one_frame_per_frame_of_the_shot(self):
        with tempfile.TemporaryDirectory() as tmp:  # a shot of 5 frames: a window saves frames 1 to 3, the next 4 and 5
            run_window(tmp, 1, 3), run_window(tmp, 4, 2), run_window(tmp, 4, 2)
            self.assertEqual(sorted(os.listdir(tmp)), [f"matte_{k:05}_.png" for k in range(1, 6)])

    def test_numbered_on_from_the_files_there_a_second_run_adds_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_window(tmp, 0, 3), run_window(tmp, 0, 2), run_window(tmp, 0, 2)
            self.assertEqual(len(os.listdir(tmp)), 7)


if __name__ == "__main__":
    unittest.main()
