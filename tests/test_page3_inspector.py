"""The colour inspector's average (routes.pixel, `pts`): the mean of the points sampled with Shift held, read from the
frame the point is read from, each point at the same place of the picture as in the plate's grid."""
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from _env import require
require("aiohttp")
import test_routes  # noqa: E402  (its stand-in for ComfyUI's folder_paths, then routes)

routes = test_routes.routes


class PointsSampled(unittest.TestCase):
    def read(self, **kw):
        rgb = np.arange(4 * 6 * 3, dtype=np.float32).reshape(4, 6, 3)  # a frame of 6 x 4, every value distinct
        with tempfile.TemporaryDirectory() as d:
            still = os.path.join(d, "f.png")
            open(still, "wb").close()
            with mock.patch.object(routes.folders, "plate_path", return_value=still), \
                    mock.patch.object(routes, "_frame_cached", return_value=rgb):
                return rgb, routes.pixel("f.png", 0, **kw)

    def test_mean_of_the_points(self):
        rgb, out = self.read(x=1, y=1, pts="1,1;4,2")
        self.assertEqual(out["average"], {"value": [float(v) for v in (rgb[1, 1] + rgb[2, 4]) / 2], "n": 2})

    def test_points_in_the_plates_grid(self):  # a pass half the plate's size reads each point at the same place
        rgb, out = self.read(x=2, y=2, of="12x8", pts="2,2;8,4")
        self.assertEqual((out["x"], out["y"]), (1, 1))
        self.assertEqual(out["average"]["value"], [float(v) for v in (rgb[1, 1] + rgb[2, 4]) / 2])

    def test_no_points_no_average(self):
        self.assertNotIn("average", self.read(x=0, y=0)[1])

    def test_a_point_outside_the_frame_is_refused(self):
        with self.assertRaises(ValueError):
            self.read(x=0, y=0, pts="0,0;9,9")


if __name__ == "__main__":
    unittest.main()
