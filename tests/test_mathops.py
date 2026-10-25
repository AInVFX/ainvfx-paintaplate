"""Checks for the fitting maths on synthetic frames (numpy only)."""
import os, sys
import numpy as np
from scipy import ndimage
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402

rng = np.random.default_rng(3)
H, W = 128, 192
base = ndimage.gaussian_filter(rng.random((H, W, 3)), (3, 3, 0)).astype(np.float32) * 2


def test_shift_survives_relight():
    moved = ndimage.shift(base, (1.6, -2.3, 0), order=3, mode="nearest")
    lit = moved * np.linspace(0.4, 1.8, W, dtype=np.float32)[None, :, None]  # strong light ramp
    dy, dx = m.phase_shift(m.structure(base), m.structure(lit), max_shift=8)
    assert abs(dy + 1.6) < 0.25 and abs(dx - 2.3) < 0.25, (dy, dx)
    print(f"phase shift under relight: ok ({dy:+.2f}, {dx:+.2f})")


def test_color_and_grain():
    mask = np.zeros((H, W), np.float32); mask[40:90, 60:130] = 1
    gen = base * 0.8 + 0.1
    fixed = m.match_color(gen, base, m.ring(mask, 12))
    band = m.ring(mask, 12)
    assert np.abs(fixed[band].mean(0) - base[band].mean(0)).max() < 1e-3
    plate = base + rng.normal(0, 0.03, base.shape).astype(np.float32)
    sig = m.noise_sigma(plate)
    grained = m.add_grain(base.copy(), sig, rng)
    assert np.allclose(m.noise_sigma(grained), sig, rtol=0.35), (m.noise_sigma(grained), sig)
    print("ring colour match and grain level: ok")


def test_relight_keeps_detail():
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


if __name__ == "__main__":
    test_shift_survives_relight(); test_color_and_grain(); test_relight_keeps_detail()
