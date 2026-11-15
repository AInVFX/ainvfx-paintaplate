"""Follow Matte names every frame by the plate's own number: from 1 for a movie, from the first file's number for a
sequence (`first_frame`). A recording keeps the number, so a replay's summary names the same frames."""
import glob, os, sys, tempfile, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


def zone_only(n=6, h=60, w=120):
    """A paint whose tracker returns nothing: the matte holds the paint zone, 60 times the object, on every frame."""
    first, element = np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
    first[10:50, 10:100] = 1
    element[30:36, 20:30] = 1
    return dict(masks=np.zeros((0, h, w), np.float32), n=n, first=first, element=element)


class PlateNumbers(unittest.TestCase):
    def test_every_frame_named_is_the_plates(self):
        text = m.follow_summary(121, 100, placed=2, moved=3, left=(14, 20), largest=(33.1, 64), above=(24, 89),
                                flicker=(5, 0.59, 52), first_frame=480)
        for line in ("Warning: object left its place at frame 494.", "from frame 504 to 569 (up to 33.1x at frame 544).",
                     "its place of frame 480 added", "Object moves from frame 483:", "whole matte from frame 500 (",
                     "of the matte at frame 532)."):
            self.assertIn(line, text)

    def test_a_movie_counts_from_1(self):
        self.assertIn("Warning: matte 4.2x the object at frame 1.", m.follow_summary(121, 100, largest=(4.2, 0), above=(0, 0)))

    def test_follow_matte_names_the_plates_frames(self):
        self.assertIn("from frame 1 to 6 (up to 60.0x at frame 1).", m.follow_matte(**zone_only())[1])
        self.assertIn("from frame 480 to 485 (up to 60.0x at frame 480).", m.follow_matte(**zone_only(), first_frame=480)[1])

    def test_a_replay_names_the_same_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            os.environ["PAINTAPLATE_RECORD"] = folder
            try:
                live = m.follow_matte(**zone_only(), first_frame=480)[1]
            finally:
                del os.environ["PAINTAPLATE_RECORD"]
            path, = glob.glob(os.path.join(folder, "*.npz"))
            args = m.replay(path)
            self.assertEqual(args["first_frame"], 480)
            self.assertEqual(m.follow_matte(**args)[1], live)
            with np.load(path) as d:  # a recording that holds no number replays as a movie
                old = {k: d[k] for k in d.files if k != "first_frame"}
            np.savez_compressed(path, **old)
            self.assertEqual(m.replay(path)["first_frame"], 1)


if __name__ == "__main__":
    unittest.main()
