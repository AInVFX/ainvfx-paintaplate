"""Fit to Plate's colour match leaves a painted object as the shot made it. The shot drifts in colour against the plate,
as an LTX shot can; the colour match brings the edge the composite adds around the matte back to the plate. With the
paint matte as `keep`, the painted object keeps the colours the shot gave it; without it, as for a cleaned area, the
whole inside of the matte follows the plate's colours."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mathops  # noqa: E402

H, W, N = 240, 320, 3


def scene():
    """A blue-grey plate; a shot with a warm drift of 12% in red everywhere and a cream object; the object's matte."""
    yy, xx = np.mgrid[:H, :W]
    plate = np.stack([np.full((H, W), 0.30), np.full((H, W), 0.45), np.full((H, W), 0.55)], -1).astype(np.float32)
    shot = plate * np.array([1.12, 1.0, 1.0], np.float32)
    obj = (np.abs(xx - 160) < 50) & (np.abs(yy - 120) < 40)
    shot[obj] = (0.90, 0.85, 0.72)
    return plate, shot, obj.astype(np.float32)


class KeepsPaintedColours(unittest.TestCase):
    def fit(self, keep):
        plate, shot, matte = scene()
        images, masks = mathops.fit_to_plate(N, H, W, lambda i: plate, lambda i: shot, matte[None], align=False, grain=0.0,
                                             grow=8, feather=12, steady=0, workers=1, keep=None if keep is None else matte[None])
        return plate, shot, matte > 0.5, images[1], masks[1]

    def test_a_painted_object_keeps_the_shots_colours(self):
        plate, shot, obj, out, mask = self.fit(keep=True)
        inner = np.zeros_like(obj); inner[90:150, 120:200] = True  # well inside the object
        self.assertLess(float(np.abs(out[inner] - shot[inner]).max()), 0.01, "the painted object keeps the colours the shot gave it")
        ring = (mask > 0.5) & ~obj  # the edge the composite adds around it
        self.assertLess(float(np.abs(out[ring][:, 0] - plate[ring][:, 0]).mean()), 0.25 * float(np.abs(shot[ring][:, 0] - plate[ring][:, 0]).mean()),
                        "the edge around it comes back to the plate's colour")

    def test_without_keep_the_inside_follows_the_plate_as_for_a_cleaned_area(self):
        plate, shot, obj, out, mask = self.fit(keep=None)
        inner = np.zeros_like(obj); inner[90:150, 120:200] = True
        self.assertGreater(float(np.abs(out[inner] - shot[inner]).max()), 0.03, "the colour match reaches the inside of the matte")


if __name__ == "__main__":
    unittest.main()
