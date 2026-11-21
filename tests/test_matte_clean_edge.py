"""Fit to Plate for a Clean: the composite grows the matte by a wide margin, so it takes all of the object, its soft
edges and what it blurs. The margin's first stretch, as wide as its feather, always grows: on a background full of edges
(bricks, leaves, a fence) the object's rim and its outline still go whole. The rest stops at the edges the plate and the
clean plate both keep, the outline of what stays beside the object (a person, a window frame), so the composite never
takes a regenerated person. Away from such an edge the margin keeps its whole width, and a painted object (keep) grows
as before."""
import os
import sys
import unittest

import numpy as np
from scipy import ndimage

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


def backdrop(kind):
    """A background full of edges that the clean plate keeps, at 480 x 240."""
    yy, xx = np.mgrid[:H, :W]
    if kind == "bricks":  # mortar lines every 24 x 12 px
        b = np.full((H, W, 3), (0.55, 0.3, 0.22), np.float32)
        b[(yy % 12 < 2) | ((xx + 12 * ((yy // 12) % 2)) % 24 < 2)] = (0.8, 0.78, 0.72)
    elif kind == "leaves":  # light and dark blobs a few pixels across
        n = ndimage.gaussian_filter(np.random.default_rng(1).random((H, W)), 2)
        n = n > np.median(n)
        b = np.stack([0.15 + 0.3 * n, 0.3 + 0.45 * n, 0.1 + 0.2 * n], -1).astype(np.float32)
    else:  # a fence: rails and posts in front of a field
        b = np.stack([0.35 + 0.0 * xx, 0.5 + 0.1 * yy / H, 0.25 + 0.0 * xx], -1).astype(np.float32)
        b[(yy % 45 < 7) | (xx % 80 < 6)] = (0.3, 0.2, 0.12)
    return b


class CleanMargin(unittest.TestCase):
    def test_on_a_background_full_of_edges_the_object_and_its_outline_go_whole(self):
        yy, xx = np.mgrid[:H, :W]
        obj = ((xx - 240) / 55.0) ** 2 + ((yy - 120) / 75.0) ** 2 <= 1
        fringe = ndimage.binary_dilation(obj, iterations=2) & ~obj  # the outline's soft pixels, which a tracker's matte leaves out
        for kind in ("bricks", "leaves", "fence"):
            clean = backdrop(kind)
            plate = clean.copy(); plate[obj] = (0.85, 0.2, 0.2); plate[fringe] = 0.5 * plate[fringe] + (0.42, 0.1, 0.1)
            _, masks = mathops.fit_to_plate(N, H, W, lambda i: plate, lambda i: clean, obj.astype(np.float32)[None], align=False, match_color=False,
                                            grain=0.0, grow=20, feather=5, steady=0, workers=1)  # a Clean's margin at this width: a 24th and a 96th
            with self.subTest(kind):
                self.assertGreater(float(masks[1][obj].min()), 0.95, "the composite takes all of the object, its rim included")
                self.assertGreater(float(masks[1][fringe].mean()), 0.9, "and the soft pixels of its outline")


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
