"""Follow Matte's margin rule when the plate's pan is read exactly: the covered part it adds around the object's place
is a thick area, so the edge of what stands in front stays out of the matte."""
import sys
import unittest
from unittest import mock

from _env import ROOT, require

require("numpy", "scipy")
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import mathops  # noqa: E402
import test_matte_comeback  # noqa: E402


class Margin(unittest.TestCase):
    def test_the_edge_of_what_stands_in_front_stays_out_when_the_pan_is_read_exactly(self):
        sam, shown, shot, base, front = test_matte_comeback.scene()  # a pan of 2 px a frame; something stands in front, still in the frame
        with mock.patch.object(mathops, "plate_move", lambda before, after: (0.0, -2.0)):
            matte, _ = mathops.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, zone=1 / 16, threshold=0.1,
                                            element=shown[0].astype(np.float32))
        self.assertEqual(int((matte[(slice(20, None),) + front] > 0.5).sum()), 0)


if __name__ == "__main__":
    unittest.main()
