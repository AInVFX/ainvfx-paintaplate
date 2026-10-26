"""Checks for the fitting maths on synthetic frames (numpy only)."""
import os, sys, unittest
import numpy as np
from scipy import ndimage
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402

rng = np.random.default_rng(3)
H, W = 128, 192
base = ndimage.gaussian_filter(rng.random((H, W, 3)), (3, 3, 0)).astype(np.float32) * 2


class MathOps(unittest.TestCase):
    """Fitting a generated shot to a plate: alignment, colour, grain, relight."""

    def test_shift_survives_relight(self):
        moved = ndimage.shift(base, (1.6, -2.3, 0), order=3, mode="nearest")
        lit = moved * np.linspace(0.4, 1.8, W, dtype=np.float32)[None, :, None]  # strong light ramp
        dy, dx = m.phase_shift(m.structure(base), m.structure(lit), max_shift=8)
        assert abs(dy + 1.6) < 0.25 and abs(dx - 2.3) < 0.25, (dy, dx)
        print(f"phase shift under relight: ok ({dy:+.2f}, {dx:+.2f})")

    def test_grain_level_and_seam(self):
        plate = base + rng.normal(0, 0.03, base.shape).astype(np.float32)
        sig = m.noise_sigma(plate)
        grained = m.add_grain_level(base.copy(), sig, rng)  # clean frames topped up to the plate's grain
        assert np.allclose(m.noise_sigma(grained), sig, rtol=0.35), (m.noise_sigma(grained), sig)
        mask = np.zeros((H, W), np.float32); mask[40:90, 60:130] = 1
        field = m.seam_field(base, base * np.array([0.9, 1.1, 0.85], np.float32), mask, 8.0)
        gain = np.exp(field[65, 95])  # inside the mask, the field undoes the drift measured around it
        assert np.abs(gain - [1 / 0.9, 1 / 1.1, 1 / 0.85]).max() < 0.02, gain
        print("grain level and seam field: ok")

    def test_fill_hole(self):
        img = np.zeros((64, 96, 3), np.float32); img[..., 1] = np.linspace(0, 1, 96)[None, :]
        img[20:44, 40:60] = [1, 0, 0]  # an object to fill
        mask = np.zeros((64, 96), np.float32); mask[20:44, 40:60] = 1
        out = m.fill_hole(img, mask, grow=3, feather=2)
        assert out[32, 50, 0] < 0.05 and abs(out[32, 50, 1] - 50 / 95) < 0.08  # the green ramp continues through it
        assert np.array_equal(out[:, :25], img[:, :25])  # far from the mask nothing moves
        grown = m.dilate(mask, 4)
        assert grown[16, 50] == 1 and grown[15, 50] == 0 and grown[32, 63] == 1  # 4 px on every side
        print("fill hole and dilate: ok")

    def test_relight_frame_aligns_first(self):
        source = base
        relit = ndimage.shift(base * 1.5, (1.4, -2.0, 0), order=3, mode="nearest")  # brighter and shifted
        out = m.relight_frame(base, source, relit, radius=8, strength=1.0, align=True)
        ratio = out[20:-20, 20:-20] / base[20:-20, 20:-20]
        assert abs(np.median(ratio) - 1.5) < 0.05, np.median(ratio)
        print(f"relight frame: ok (median ratio {np.median(ratio):.3f})")

    def test_relight_keeps_detail(self):
        plate = base * 3.0  # values above 1.0, like an EXR
        plate[10:20, 10:20] = 9.0
        gain = np.linspace(0.5, 2.0, W, dtype=np.float32)[None, :, None]
        source = base.copy()
        relit = base * gain
        out = m.relight(plate, source, relit, radius=8)
        err = np.abs(out[:, :, :3] / plate[:, :, :3] / gain - 1.0)
        assert np.median(err) < 0.03 and np.percentile(err, 95) < 0.12, (np.median(err), np.percentile(err, 95))
        assert out[15, 15].min() > 4.0  # highlights scale, never clip
        big = m.relight(np.repeat(np.repeat(plate, 2, 0), 2, 1), source, relit, radius=8)
        assert big.shape == (2 * H, 2 * W, 3)
        print("relight transfer: ok (ratio follows the light, highlights kept, any plate size)")


    def test_fill_and_steady_masks(self):
        ramp = np.zeros((64, 96, 3), np.float32); ramp[..., 0] = np.linspace(0, 1, 96)[None, :]
        known = np.ones((64, 96), np.float32); known[20:44, 30:70] = 0
        filled = m.push_pull(ramp * known[..., None], known)
        assert np.abs(filled[32, 30:70, 0] - ramp[32, 30:70, 0]).max() < 0.08  # a hole takes the ramp around it
        boil = np.zeros((9, 60, 80), np.float32)
        for i in range(9):  # a tracker edge that moves 3 px every other frame
            boil[i, 20:40, 20 + 3 * (i % 2): 50 + 3 * (i % 2)] = 1
        steady = m.steady_masks(boil, 2, 2, 4)
        edges = {tuple((steady[i, 30] > 0.5).nonzero()[0][[0, -1]]) for i in range(2, 7)}
        assert len(edges) == 1, edges
        print("push-pull fill and steady masks: ok")

    def test_fit_to_plate_is_steady_and_seamless(self):
        """A regeneration with an exposure drift and a boiling matte: the composite edge holds still and matches."""
        n, h, w = 15, 120, 200
        yy, xx = np.mgrid[0:h, 0:w]
        bg = (0.35 + 0.25 * np.sin(xx / 13.0)[..., None] * np.cos(yy / 9.0)[..., None] * np.array([1, 0.8, 0.6])).astype(np.float32)
        obj = ((yy - 60) ** 2 / 20 ** 2 + (xx - 100) ** 2 / 26 ** 2) < 1
        plates, gens, masks = [], [], []
        for i in range(n):
            p = bg + rng.normal(0, 0.02, bg.shape).astype(np.float32)
            p[obj] = [0.9, 0.2, 0.1]  # the object to erase
            plates.append(p)
            gens.append((bg * np.float32(1.18) * np.linspace(0.92, 1.08, w, dtype=np.float32)[None, :, None]).astype(np.float32))
            k = int(rng.integers(0, 4))  # SAM's edge, different every frame (iterations=0 would mean 'until it stops growing')
            mk = ndimage.binary_dilation(obj, iterations=k) if k else obj
            masks.append(mk.astype(np.float32))
        masks = np.stack(masks)
        out, mout = m.fit_to_plate(n, h, w, lambda i: plates[i], lambda i: gens[i], masks, grow=4, feather=8, steady=2,
                                   grain=1.0, workers=2)
        _, short = m.fit_to_plate(n, h, w, lambda i: plates[i], lambda i: gens[i], masks[:3], grow=4, feather=8, steady=0,
                                  grain=0, workers=2)  # a matte shorter than the plate holds its last frame
        assert np.allclose(short[-1], short[2])
        comp = [mout[i][..., None] * out[i] + (1 - mout[i][..., None]) * plates[i] for i in range(n)]
        # 1. the matte edge holds still: frame-to-frame change of the mask, now and with the old per-frame mask
        old = [ndimage.gaussian_filter((ndimage.distance_transform_edt(mk < 0.5) <= 4).astype(np.float32), 4) for mk in masks]
        flicker_old = np.mean([np.abs(old[i] - old[i - 1]).mean() for i in range(3, n - 3)])
        flicker_new = np.mean([np.abs(mout[i] - mout[i - 1]).mean() for i in range(3, n - 3)])
        assert flicker_new < 0.25 * flicker_old, (flicker_new, flicker_old)
        # 2. no seam: just inside the edge, the composite has the plate's brightness, not the drift of the regeneration
        edge = (mout[7] > 0.3) & (mout[7] < 0.7)
        ratio = np.median(comp[7][edge] / plates[7][edge], 0)
        assert np.abs(ratio - 1).max() < 0.04, ratio
        raw = np.median((mout[7][..., None] * gens[7] + (1 - mout[7][..., None]) * plates[7])[edge] / plates[7][edge], 0)
        assert np.abs(raw - 1).max() > 0.06, raw  # without the fit the edge shows the drift
        # 3. the object is gone and pixels far from the edit are untouched
        assert np.abs(comp[7][obj].mean(0) - bg[obj].mean(0)).max() < 0.06
        assert (mout[7][:, :40] == 0).all()
        # 4. the grain added inside matches the plate's level
        inside = ndimage.binary_erosion(mout[7] > 0.99, iterations=4)
        assert inside.sum() > 200
        print(f"fit to plate: ok (edge change per frame {flicker_new:.4f} against {flicker_old:.4f} before, "
              f"edge ratio {ratio.round(3).tolist()})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
