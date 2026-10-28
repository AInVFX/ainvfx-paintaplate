"""Checks for the fitting maths on synthetic frames (numpy only)."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
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

    def test_dilate(self):
        mask = np.zeros((64, 96), np.float32); mask[20:44, 40:60] = 1
        grown = m.dilate(mask, 4)
        assert grown[16, 50] == 1 and grown[15, 50] == 0 and grown[32, 63] == 1  # 4 px on every side
        print("dilate: ok")

    def test_relight_frame_aligns_first(self):
        source = base
        relit = ndimage.shift(base * 1.5, (1.4, -2.0, 0), order=3, mode="nearest")  # brighter and shifted
        out = m.relight_frame(base, source, relit, radius=8, strength=1.0, align=True)
        ratio = out[20:-20, 20:-20] / base[20:-20, 20:-20]
        assert abs(np.median(ratio) - 1.5) < 0.05, np.median(ratio)
        half = lambda im: ndimage.zoom(im, (0.5, 0.5, 1), order=1)  # noqa: E731
        small = m.relight_frame(base, half(source), half(relit), radius=4, strength=1.0, align=True)
        assert small.shape == base.shape  # measured at half size, applied at the plate's
        assert abs(np.median(small[20:-20, 20:-20] / base[20:-20, 20:-20]) - 1.5) < 0.05
        print(f"relight frame: ok (median ratio {np.median(ratio):.3f}, the same from half-size inputs)")

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

    def test_box_matte_hides_the_outline(self):
        mask = np.zeros((2, 40, 60), np.float32)
        mask[0, 10:20, 20:30] = 1  # a 10 x 10 object; the second frame is empty
        box = m.box_matte(mask, 0.5)
        self.assertEqual(box[0].sum(), 20 * 20)  # grown by half its size on each side
        self.assertEqual(box[1].sum(), 0)


class Keyframes(unittest.TestCase):
    def test_keyframe_video(self):
        """Black frames, each key at its frame (clamped), the later of two keys on one frame winning."""
        images = {"a": np.full((4, 6, 3), 0.8, np.float32), "b": np.full((4, 6, 3), 0.3, np.float32)}
        video = m.keyframe_video([{"frame": 0, "image": "a"}, {"frame": 99, "image": "b"}, {"frame": 0, "image": "b"}],
                                       6, 4, 9, images.__getitem__)
        self.assertEqual(video.shape, (9, 4, 6, 3))
        self.assertAlmostEqual(float(video[0].mean()), 0.3, places=5)
        self.assertAlmostEqual(float(video[8].mean()), 0.3, places=5)  # frame 99 clamped to the last frame
        self.assertEqual(float(video[1:8].max()), 0.0)

class ResizeTo(unittest.TestCase):
    def test_resize_matches_scipy_zoom(self):
        """resize_to gives scipy's zoom (order 1, grid_mode, edges clamped), larger and smaller, colour and masks."""
        img = np.random.default_rng(3).random((37, 53, 3), dtype=np.float32)
        for h, w in ((64, 90), (20, 31), (37, 80)):
            ref = ndimage.zoom(img, (h / 37, w / 53, 1), order=1, grid_mode=True, mode="nearest")
            got = m.resize_to(img, h, w)
            self.assertEqual(got.shape, (h, w, 3))
            self.assertLess(float(np.abs(got - ref).max()), 1e-5)
        mask = ndimage.zoom(img[..., 0], (20 / 37, 31 / 53), order=1, grid_mode=True, mode="nearest")
        self.assertLess(float(np.abs(m.resize_to(img[..., 0], 20, 31) - mask).max()), 1e-5)
        self.assertIs(m.resize_to(img, 37, 53), img)  # the same size: no copy

    def test_follow_matte(self):
        n, h, w = 12, 60, 120
        shot = np.zeros((n, h, w, 3), np.float32)
        base = np.zeros_like(shot)
        sam = np.zeros((n, h, w), np.float32)
        for t in range(n):  # a car that drives right, a flame above it that SAM never sees, then SAM loses the car too
            x = 20 + t
            shot[t, 30:40, x:x + 15] = 0.9
            shot[t, 20:30, x + 4:x + 10] = 0.8
            if t < 8:
                sam[t, 30:40, x:x + 15] = 1
        first = sam[0].copy()
        shot[:, 5:15, 90:110] = 0.5  # far away, the regenerated smoke differs from the plate's, and SAM finds a stray object in it
        sam[3:, 8:12, 95:100] = 1
        out, summary = m.follow_matte(sam, n, first, shot, base, zone=0.25)
        self.assertEqual(out.shape, (n, h, w))
        for t in range(n):  # the flame and the car stay in every frame, also after SAM lost them
            self.assertEqual(out[t, 25, 20 + t + 6], 1, t)
            self.assertEqual(out[t, 35, 20 + t + 7], 1, t)
        self.assertEqual(out[:, :, :12].max(), 0)  # what the shot did not change stays out
        self.assertEqual(out[:, :, 80:].max(), 0)  # the stray object and the changes around it are left out
        self.assertIn("on 8 of 12", summary)
        self.assertIn("left out", summary)
        held, summary = m.follow_matte(np.zeros((0, h, w), np.float32), n, first)  # SAM returned no mask
        self.assertTrue((held == (first > 0.5)).all())
        self.assertIn("no mask", summary)
        part, _ = m.follow_matte(sam[:3], n, first)  # fewer masks than frames: the last matte holds
        self.assertTrue((part[11] == part[2]).all())
        erase, start = np.zeros((n, h, w), np.float32), np.zeros((h, w), np.float32)  # an erase: a gap, then further on
        start[30:40, 20:30] = 1
        for t in (0, 1, 2, 3, 7, 8):
            x = 20 + (3 * t if t < 4 else 6 * t)
            erase[t, 30:40, x:x + 10] = 1
        erase[:, 0:4, 116:120] = 1  # a stray object on every frame
        out, summary = m.follow_matte(erase, n, start, zone=0.1)
        self.assertEqual(out[:, 0:4, 116:120].max(), 0)  # the stray is left out
        self.assertTrue((out[5] == out[3]).all())  # the gap holds the last matte
        self.assertEqual(out[7, 35, 66], 1)  # found again further on: the search grew over the gap
        self.assertIn("on 6 of 12", summary)
        blob = np.zeros((n, h, w), np.float32)  # SAM's first mask is the whole paint zone; then it splits in two
        blob[0, 10:50, 10:100] = 1
        blob[1:, 30:40, 20:35] = 1
        blob[1:, 10:20, 85:95] = 1
        blob[1:, 15, 35:86] = 1  # joined to the element by a thin line, as SAM joined a smoke plume's edges to a car
        blob[1:, 15:31, 35] = 1
        element = np.zeros((h, w), np.float32)  # what the edit changed: the element only
        element[30:40, 20:35] = 1
        out, _ = m.follow_matte(blob, n, blob[0], element=element, zone=0.1)
        self.assertEqual(out[0, 15, 90], 0)  # the zone's far side, where the edit changed nothing, is left out from frame 0
        self.assertEqual(out[5, 35, 25], 1)  # the element stays
        self.assertEqual(out[5, 15, 90], 0)  # the far piece is left out, though a thin line joins it to the element

if __name__ == "__main__":
    unittest.main(verbosity=2)
