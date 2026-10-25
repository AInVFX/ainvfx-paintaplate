"""Small numpy helpers that fit generated pixels back onto the plate.

Each function works on one frame, (H, W, C) float arrays, so it is easy to test.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

REC709 = np.array([0.2126, 0.7152, 0.0722], np.float32)


def luma(img: np.ndarray) -> np.ndarray:
    return img[..., :3] @ REC709


def structure(img: np.ndarray, sigma: float = 8.0) -> np.ndarray:
    """Log luma minus its blur: edges and texture, with the lighting removed.

    Two frames that differ only by their light give similar structure maps, so
    alignment still works after a relight.
    """
    log = np.log(np.maximum(luma(img), 0.0) + 1e-3)
    return log - ndimage.gaussian_filter(log, sigma)


def phase_shift(ref: np.ndarray, img: np.ndarray, max_shift: float) -> tuple[float, float]:
    """Sub-pixel (dy, dx) that moves `img` onto `ref` (2D float arrays)."""
    h, w = ref.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    fa, fb = np.fft.rfft2(ref * win), np.fft.rfft2(img * win)
    cross = fa * np.conj(fb)
    corr = np.fft.irfft2(cross / (np.abs(cross) + 1e-9), s=(h, w))
    py, px = np.unravel_index(np.argmax(corr), corr.shape)

    def refine(c_m, c_0, c_p):  # parabola through three samples around the peak
        d = c_m - 2 * c_0 + c_p
        return 0.0 if abs(d) < 1e-12 else 0.5 * (c_m - c_p) / d

    dy = py + refine(corr[py - 1, px], corr[py, px], corr[(py + 1) % h, px])
    dx = px + refine(corr[py, px - 1], corr[py, px], corr[py, (px + 1) % w])
    dy = dy - h if dy > h / 2 else dy
    dx = dx - w if dx > w / 2 else dx
    if abs(dy) > max_shift or abs(dx) > max_shift:
        return 0.0, 0.0  # not a small misalignment: leave the frame alone
    return float(dy), float(dx)


def ring(mask: np.ndarray, width: int) -> np.ndarray:
    """Pixels just outside a mask: where plate and generated pixels must agree."""
    inside = mask > 0.5
    dist = ndimage.distance_transform_edt(~inside)
    return (dist > 0) & (dist <= width)


def match_color(img: np.ndarray, plate: np.ndarray, band: np.ndarray) -> np.ndarray:
    """Match mean and contrast per channel to the plate over the ring `band`."""
    if band.sum() < 64:
        return img
    out = img.copy()
    for c in range(3):
        a, b = img[..., c][band], plate[..., c][band]
        scale = np.clip(b.std() / max(a.std(), 1e-6), 0.5, 2.0)
        out[..., c] = (img[..., c] - a.mean()) * scale + b.mean()
    return out


def noise_sigma(img: np.ndarray) -> np.ndarray:
    """Per-channel grain level: robust spread of the fine detail in flat areas."""
    sig = np.zeros(3, np.float32)
    flat = ndimage.gaussian_filter(np.abs(ndimage.sobel(luma(img))), 2.0)
    keep = flat < np.percentile(flat, 30)
    for c in range(3):
        detail = img[..., c] - ndimage.gaussian_filter(img[..., c], 1.0)
        v = detail[keep]
        sig[c] = 1.4826 * np.median(np.abs(v - np.median(v)))
    return sig


def add_grain(img: np.ndarray, target: np.ndarray, rng: np.random.Generator,
              strength: float = 1.0) -> np.ndarray:
    """Top up the grain of `img` to the `target` per-channel level."""
    missing = np.sqrt(np.maximum(target**2 - noise_sigma(img) ** 2, 0.0)) * strength
    if not np.any(missing > 0):
        return img
    noise = rng.standard_normal(img.shape[:2] + (3,)).astype(np.float32)
    noise = ndimage.gaussian_filter(noise, (0.6, 0.6, 0))  # soft grain, not pixel noise
    # Scale by how the estimator sees this grain, so measured levels match.
    out = img.copy()
    out[..., :3] += noise * (missing / np.maximum(noise_sigma(noise), 1e-6))
    return out


def box(x: np.ndarray, r: int) -> np.ndarray:
    return ndimage.uniform_filter(x, size=(2 * r + 1, 2 * r + 1) + (1,) * (x.ndim - 2), mode="reflect")


def guided_filter(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """Edge-aware smoothing of `src` (H, W, C) following a gray `guide` (H, W)."""
    g = guide[..., None]
    mean_g, mean_s = box(g, r), box(src, r)
    cov = box(g * src, r) - mean_g * mean_s
    var = box(g * g, r) - mean_g**2
    a = cov / (var + eps)
    b = mean_s - a * mean_g
    return box(a, r) * g + box(b, r)


def relight(plate: np.ndarray, source: np.ndarray, relit: np.ndarray,
            radius: int, strength: float = 1.0) -> np.ndarray:
    """Move the light of `relit` onto `plate`, keeping the plate's own detail.

    All three images are linear light. `source` and `relit` share the working
    size; `plate` can be larger. The change of light is the ratio relit/source,
    smoothed with an edge-aware filter; the plate is multiplied by it, so its
    texture, grain and values above 1.0 stay its own.
    """
    guide = np.log(luma(source).clip(0) + 1e-3)
    eps = 1e-3 * max(guide.var(), 1e-6)
    ratio = (guided_filter(guide, relit[..., :3].clip(0), radius, eps) + 1e-4) / \
            (guided_filter(guide, source[..., :3].clip(0), radius, eps) + 1e-4)
    ratio = np.clip(ratio, 0.0, 16.0) ** strength
    if ratio.shape[:2] != plate.shape[:2]:
        zoom = (plate.shape[0] / ratio.shape[0], plate.shape[1] / ratio.shape[1], 1)
        ratio = ndimage.zoom(ratio, zoom, order=1)[: plate.shape[0], : plate.shape[1]]
    out = plate.copy()
    out[..., :3] = plate[..., :3] * ratio
    return out
