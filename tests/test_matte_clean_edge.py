"""Fit to Plate for a Clean: the composite grows the matte by a wide margin, so it takes all of the object, its soft
edges and what it blurs; that margin stops at the edges the plate and the clean plate both keep, the outline of what
stays beside the object (a person, a window frame), so the composite never takes a regenerated person. Away from
such an edge the margin keeps its whole width, and a painted object (keep) grows as before."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mathops  # noqa: E402

H, W, N = 240, 480, 3


def scene():
    """A smooth sky, a person (a dark block with a sharp outline) at x 300 to 400, and leaves to clean at x 230 to 290,
    10 px from her; the clean plate shows the sky where the leaves were, and the same person."""
    yy, xx = np.mgrid[:H, :W]
    sky = np.stack([0.55 + 0.1 * yy / H, 0.65 + 0.1 * yy / H, 0.8 + 0.0 * xx], -1).astype(np.float32)
    person = (xx >= 300) & (xx < 400) & (yy >= 60)
    plate = sky.copy(); plate[person] = (0.35, 0.22, 0.15)
    leaves = (xx >= 230) & (xx < 290) & (yy >= 40) & (yy < 200)
    plate[leaves & ((xx // 6 + yy // 6) % 2 == 0)] = (0.1, 0.35, 0.1)
    clean = sky.copy(); clean[person] = (0.36, 0.20, 0.16)  # the clean plate pass: the person again, nearly the same
    return plate, clean, leaves.astype(np.float32), person


class CleanMargin(unittest.TestCase):
    def fit(self, keep=None):
        plate, clean, matte, person = scene()
        _, masks = mathops.fit_to_plate(N, H, W, lambda i: plate, lambda i: clean, matte[None], align=False, match_color=False, grain=0.0,
                                        grow=40, feather=8, steady=0, workers=1, keep=keep)
        return masks[1], matte > 0.5, person

    def test_the_margin_stops_at_the_person_beside_the_cleaned_leaves(self):
        mask, leaves, person = self.fit()
        self.assertGreater(float(mask[leaves].min()), 0.9, "all of the leaves are in the matte")
        inside = person & (np.mgrid[:H, :W][1] >= 304)  # the person, past her outline
        self.assertLess(float(mask[inside].max()), 0.2, "the margin does not reach into the person")
        self.assertGreater(float(mask[120, 200]), 0.9, "on the sky side, the margin keeps its width")

    def test_a_painted_object_grows_as_before(self):
        mask, leaves, person = self.fit(keep=scene()[2][None])
        self.assertGreater(float(mask[120, 320]), 0.5, "a paint's margin is not stopped")


if __name__ == "__main__":
    unittest.main()
