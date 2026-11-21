"""Follow Matte for a painted plume of smoke drifting over a row of trunks. Where the smoke is thin, the shot barely
changes the plate, so the change has gaps across the plume: the trunks seen through it. The matte keeps what the
tracker found in a gap of the change narrower than half a zone across, so the composite keeps the smoke whole; a
wider gap, or what lies outside the tracker's mask, stays out."""
import os
import sys
import unittest

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mathops  # noqa: E402

N, H, W = 12, 180, 320


def scene(trunk=6):
    """A plume (the tracker's mask) the shot paints grey, except along trunks `trunk` px wide, every 40 px, where the
    smoke is too thin to change the plate; and one gap 30 px wide, which is a real gap."""
    rng = np.random.default_rng(5)
    plate = (ndimage.gaussian_filter(rng.random((H, W, 3)), (1.2, 1.2, 0)) * 0.5 + 0.2).astype(np.float32)
    base, shot = np.repeat(plate[None], N, 0), np.repeat(plate[None], N, 0)
    yy, xx = np.mgrid[:H, :W]
    plume = ((xx - 160) / 110.0) ** 2 + ((yy - 90) / 60.0) ** 2 <= 1
    trunks = np.zeros((H, W), bool)
    for x0 in range(75, 245, 40):
        trunks |= (xx >= x0) & (xx < x0 + trunk)
    wide = (xx >= 230) & (xx < 260)
    painted = plume & ~trunks & ~wide
    shot[:, painted] = (0.55, 0.55, 0.57)
    masks = np.repeat(plume[None].astype(np.float32), N, 0)
    return dict(masks=masks, n=N, first=plume.astype(np.float32), shot=shot, base=base, element=painted.astype(np.float32)), plume, trunks, wide


class ThinSmoke(unittest.TestCase):
    def test_the_trunks_seen_through_thin_smoke_stay_in_the_matte(self):
        args, plume, trunks, wide = scene()
        mattes, summary = mathops.follow_matte(**args, workers=1)
        inside = plume & trunks & ~wide
        for t in range(N):
            got = mattes[t] > 0.5
            self.assertGreaterEqual(int((got & inside).sum()), 0.95 * int(inside.sum()), f"frame {t}: the thin smoke over the trunks\n{summary}")
            self.assertLess(int((got & plume & wide).sum()), 0.5 * int((plume & wide).sum()), f"frame {t}: a gap 30 px wide stays out")
            self.assertEqual(int((got & ~ndimage.binary_dilation(plume, iterations=3)).sum()), 0, f"frame {t}: nothing beyond the tracker's mask")


    def test_unchanged_parts_of_a_larger_tracked_object_between_two_painted_patches_stay_out(self):
        rng = np.random.default_rng(5)
        plate = (ndimage.gaussian_filter(rng.random((H, W, 3)), (1.2, 1.2, 0)) * 0.5 + 0.2).astype(np.float32)
        base, shot = np.repeat(plate[None], N, 0), np.repeat(plate[None], N, 0)
        yy, xx = np.mgrid[:H, :W]
        body = ((xx - 160) / 120.0) ** 2 + ((yy - 90) / 70.0) ** 2 <= 1  # the tracker returns a whole horse
        patches = ((xx >= 110) & (xx < 155) | (xx >= 165) & (xx < 210)) & (np.abs(yy - 90) < 25)  # two painted patches, 10 px apart
        shot[:, patches] = (0.7, 0.72, 0.75)
        args = dict(masks=np.repeat(body[None].astype(np.float32), N, 0), n=N, first=patches.astype(np.float32), shot=shot, base=base,
                    element=patches.astype(np.float32))
        mattes, summary = mathops.follow_matte(**args, workers=1)
        gap = (xx >= 158) & (xx < 162) & (np.abs(yy - 90) < 20)  # the middle of the gap: every kept piece grows by one pixel
        for t in range(N):
            self.assertEqual(int(((mattes[t] > 0.5) & gap).sum()), 0, f"frame {t}: the horse between the patches stays out\n{summary}")


if __name__ == "__main__":
    unittest.main()
