"""The numpy maths behind the nodes: fitting generated frames to the plate, compositing, filling an erase, relighting,
mattes that follow an object, the HDR level and the keyframe video.

Frames are (H, W, C) float arrays and masks (H, W); stacks add a first axis. Nothing here imports
torch or ComfyUI, so every function is tested in plain Python (tests/test_mathops.py).
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy import ndimage

MASK_SIDE = 480  # fit_to_plate works on masks and colour fields of about this long side, then enlarges them
ALIGN_SIDE = 512  # and measures alignment at about this one


def luma(img: np.ndarray) -> np.ndarray:
    """Rec. 709 luma. A weighted sum, not a matrix product: no BLAS threads inside worker threads."""
    return 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]


def structure(img: np.ndarray, sigma: float = 8.0) -> np.ndarray:
    """Log luma minus its blur: edges and texture, with the lighting removed.

    Two frames that differ only by their light give similar structure maps, so
    alignment still works after a relight.
    """
    log = np.log(np.maximum(luma(img), 0.0) + 1e-3)
    return log - ndimage.gaussian_filter(log, sigma)


def phase_shift(ref: np.ndarray, img: np.ndarray, max_shift: float, fine: bool = False) -> tuple[float, float]:
    """Sub-pixel (dy, dx) that moves `img` onto `ref` (2D float arrays): the peak of their phase correlation, found to the
    whole pixel on the inverse FFT, then refined. With `fine`, the inverse DFT is evaluated on a grid around the peak,
    twice (steps of 1/10 px over 2 px, then of 1/100 px over 0.2 px), and a shift reads to 1/100 px. Without it, a
    parabola through the peak's three samples refines it, and a sub-pixel shift reads short, since the peak is sharp:
    0.2 px reads 0.13 on a smooth texture."""
    h, w = ref.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    if not fine:
        cross = np.fft.rfft2(ref * win) * np.conj(np.fft.rfft2(img * win))
        corr = np.fft.irfft2(cross / (np.abs(cross) + 1e-9), s=(h, w))
    else:
        cross = np.fft.fft2(ref * win) * np.conj(np.fft.fft2(img * win))
        size = np.abs(cross)
        if not size.max() > 0:
            return 0.0, 0.0  # nothing to correlate
        cross /= size + 1e-9 * size.max()
        corr = np.fft.ifft2(cross).real
    py, px = np.unravel_index(np.argmax(corr), corr.shape)
    if fine:
        dy, dx = float(py - h if py > h / 2 else py), float(px - w if px > w / 2 else px)
        fy, fx = np.fft.fftfreq(h), np.fft.fftfreq(w)
        for step in (0.1, 0.01):
            ys, xs = dy + np.arange(-10, 11) * step, dx + np.arange(-10, 11) * step
            grid = (np.exp(2j * np.pi * np.outer(ys, fy)) @ cross @ np.exp(2j * np.pi * np.outer(fx, xs))).real
            iy, ix = np.unravel_index(np.argmax(grid), grid.shape)
            dy, dx = float(ys[iy]), float(xs[ix])
    else:
        def refine(c_m, c_0, c_p):  # parabola through three samples around the peak
            d = c_m - 2 * c_0 + c_p
            return 0.0 if abs(d) < 1e-12 else 0.5 * (c_m - c_p) / d

        dy = py + refine(corr[py - 1, px], corr[py, px], corr[(py + 1) % h, px])
        dx = px + refine(corr[py, px - 1], corr[py, px], corr[py, (px + 1) % w])
        dy, dx = (dy - h if dy > h / 2 else dy), (dx - w if dx > w / 2 else dx)
    if abs(dy) > max_shift or abs(dx) > max_shift:
        return 0.0, 0.0  # not a small misalignment: leave the frame alone
    return float(dy), float(dx)


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


def add_grain_level(img: np.ndarray, level: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Add soft grain of a fixed per-channel `level`, as measured by noise_sigma.

    The level is decided once per shot, so the amount of grain does not change from frame to frame.
    """
    if not np.any(level > 0):
        return img
    noise = ndimage.gaussian_filter(rng.standard_normal(img.shape[:2] + (3,)).astype(np.float32), (0.6, 0.6, 0))
    out = img.copy()
    out[..., :3] += noise * (level / GRAIN_UNIT)
    return out


def _grain_unit() -> float:
    """How noise_sigma sees unit grain from add_grain_level: measured once on a fixed noise field."""
    noise = ndimage.gaussian_filter(np.random.default_rng(0).standard_normal((256, 256, 3)).astype(np.float32), (0.6, 0.6, 0))
    return float(np.median(noise_sigma(noise)))


def shrink(img: np.ndarray, f: int) -> np.ndarray:
    """Box average by an integer factor `f` over the first two axes; the edges are cropped to a multiple of f."""
    if f <= 1:
        return img
    h, w = img.shape[0] // f * f, img.shape[1] // f * f
    x = img[:h, :w]
    return x.reshape(h // f, f, w // f, f, *x.shape[2:]).mean((1, 3))


def _axis_taps(n_in: int, n_out: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For each output index along one axis: the two input indices to blend and the weight of the second."""
    src = np.clip((np.arange(n_out, dtype=np.float64) + 0.5) * (n_in / n_out) - 0.5, 0, n_in - 1)
    i0 = np.floor(src).astype(np.intp)
    return i0, np.minimum(i0 + 1, n_in - 1), (src - i0).astype(np.float32)


AP1_LUMA = np.array([0.2722287168, 0.6740817658, 0.0536895174], np.float32)  # ACEScg's luminance weights


def keep_black(hdr: np.ndarray, sdr: np.ndarray, low: float = 0.001, high: float = 0.01) -> np.ndarray:
    """Where the SDR shot is black, its own black instead of SDR to HDR's: the IC-LoRA's frames carry noise there (on a
    16-bit fluid shot of a blank plate, 67% of the pixels below 0.01, median 6.6e-4, the channels spread by 41% of the
    luminance), while the shot they come from holds the plate's black. `hdr` and `sdr` in ACEScg, scene-linear: below
    `low` (the SDR shot's luminance) the frame takes the SDR values, above `high` SDR to HDR's, a smooth step between;
    values above 1.0 stay wherever the shot is not black. No value is below 0: ACEScct codes under 0.0729 decode to
    small negative values, which Lightricks' LTXVHDRDecodePostprocess also clamps to 0."""
    y = np.asarray(sdr[..., :3], np.float32) @ AP1_LUMA
    t = np.clip((y - low) / max(high - low, 1e-9), 0.0, 1.0)
    w = (t * t * (3.0 - 2.0 * t))[..., None]
    out = np.maximum(np.asarray(hdr, np.float32), 0.0)
    out[..., :3] = sdr[..., :3] * (1.0 - w) + out[..., :3] * w
    return out


def lanczos_taps(n_out: int, n_in: int, start: int = 0, count: int | None = None, a: int = 3):
    """Lanczos-`a` taps for output samples start..start+count of a resize from n_in to n_out samples, pixel centres
    aligned: (indices, weights), each (count, taps), the weights of a row summing to 1, edges repeated. Shrinking widens
    the kernel by the scale, so it also filters (antialiasing), as PIL's LANCZOS does."""
    count = n_out - start if count is None else count
    scale = n_in / n_out
    support = a * max(scale, 1.0)
    centre = (np.arange(start, start + count) + 0.5) * scale - 0.5
    first = np.floor(centre - support).astype(np.int64) + 1
    k = first[:, None] + np.arange(int(np.ceil(2 * support)) + 1)[None, :]
    x = (k - centre[:, None]) / max(scale, 1.0)
    wts = np.where(np.abs(x) < a, np.sinc(x) * np.sinc(x / a), 0.0)
    wts /= np.maximum(wts.sum(1, keepdims=True), 1e-12)
    return np.clip(k, 0, n_in - 1), wts.astype(np.float32)


def composite(destination: np.ndarray, source: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """`source` inside `mask` and `destination` around it: one frame, (H, W, C) float32, with a mask (H, W) in 0 to 1.

    The arithmetic of core's Image Composite Masked (mask * source + (1 - mask) * destination), so a node that calls it
    frame by frame makes that node's pictures. Core works on the whole batch: at its peak it holds
    four copies of the shot and two of its mask, 13.2 GB for 121 frames at 1920 x 1088.
    """
    m = mask[..., None].astype(np.float32)
    return m * source + (np.float32(1) - m) * destination


def resize_lanczos(img: np.ndarray, h: int, w: int, window: tuple | None = None) -> np.ndarray:
    """(H, W[, C]) float to (h, w[, C]) with a separable Lanczos-3, or only the output rows y0:y1 and columns x0:x1 of
    `window`, reading just the source pixels they need. The floor for new content enlarged to a plate's native size,
    with no clipping: values above 1.0 and below 0 stay."""
    y0, y1, x0, x1 = window or (0, h, 0, w)
    iy, wy = lanczos_taps(h, img.shape[0], y0, y1 - y0)
    ix, wx = lanczos_taps(w, img.shape[1], x0, x1 - x0)
    src = np.asarray(img, np.float32)[iy.min():iy.max() + 1, ix.min():ix.max() + 1]
    iy, ix = iy - iy.min(), ix - ix.min()
    shape = (-1,) + (1,) * (src.ndim - 1)
    rows = sum(wy[:, t].reshape(shape) * src[iy[:, t]] for t in range(iy.shape[1]))
    shape = (1, -1) + (1,) * (src.ndim - 2)
    return sum(wx[:, t].reshape(shape) * rows[:, ix[:, t]] for t in range(ix.shape[1])).astype(np.float32)


def resize_to(img: np.ndarray, h: int, w: int) -> np.ndarray:
    """Resample the first two axes to exactly (h, w): separable bilinear, pixel centres aligned, edges clamped.

    The same result as scipy's zoom (order 1, grid_mode) and torch's bilinear interpolate without align_corners, in
    about a fifth of the time (a 480 x 270 field to 1920 x 1088 on one CPU: 63 ms against 295 ms): two gathers and two
    blends in numpy, no spline machinery. fit_to_plate enlarges every mask and colour field to full size with it.
    """
    if img.shape[:2] == (h, w):
        return img
    x = img.astype(np.float32, copy=False)
    if x.shape[0] != h:
        i0, i1, wy = _axis_taps(x.shape[0], h)
        wy = wy.reshape((-1,) + (1,) * (x.ndim - 1))
        x = x[i0] * (1.0 - wy) + x[i1] * wy
    if x.shape[1] != w:
        j0, j1, wx = _axis_taps(x.shape[1], w)
        wx = wx.reshape((1, -1) + (1,) * (x.ndim - 2))
        x = x[:, j0] * (1.0 - wx) + x[:, j1] * wx
    return x


def push_pull(values: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Fill a (H, W, C) field where `weight` (H, W, 0 to 1) is zero, from the values around it.

    Weighted averages at coarser and coarser scales are blended back where the weight
    is low, so a hole takes a smooth interpolation of its border.
    """
    levels = []
    v, w = values * weight[..., None], weight.astype(np.float32)
    while min(v.shape[:2]) > 1:
        levels.append((v, w))
        ph, pw = v.shape[0] % 2, v.shape[1] % 2
        if ph or pw:
            v = np.pad(v, ((0, ph), (0, pw), (0, 0)), mode="edge")
            w = np.pad(w, ((0, ph), (0, pw)), mode="edge")
        v = v.reshape(v.shape[0] // 2, 2, v.shape[1] // 2, 2, -1).sum((1, 3))
        w = w.reshape(w.shape[0] // 2, 2, w.shape[1] // 2, 2).sum((1, 3))
    fill = v / np.maximum(w, 1e-6)[..., None]
    for lv, lw in reversed(levels):
        up = resize_to(fill, lv.shape[0], lv.shape[1])
        a = np.clip(lw, 0.0, 1.0)[..., None]
        fill = lv / np.maximum(lw, 1e-6)[..., None] * a + up * (1.0 - a)
    return fill


def _ramp(v: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """1 up to lo, 0 from hi, a straight line between."""
    return np.clip((hi - v) / (hi - lo), 0.0, 1.0)


def _box3(x: np.ndarray, axis: int) -> np.ndarray:
    """Each cell plus its two neighbours along `axis`; nothing outside the grid."""
    pad = [(0, 0)] * x.ndim
    pad[axis] = (1, 1)
    y, n = np.pad(x, pad), x.shape[axis]
    return sum(np.take(y, range(k, k + n), axis=axis) for k in range(3))


def level_fill(fill: np.ndarray, alpha: np.ndarray, base: np.ndarray, paint: np.ndarray | None = None, cell: int = 8,
               near: tuple[float, float] = (6.0, 20.0), flat: tuple[float, float] = (6.0, 14.0)) -> tuple[np.ndarray, float]:
    """An erase's fill, levelled with the background it continues: (the fill, how far it moved on average, in levels).

    Klein's fill can sit a few levels off the background around it: a pale, soft shape where the object was, which LTX
    then animates into smoke (+4 to +6 levels on a backdrop at 18). The background inside the fill is estimated
    from the frame around it on a grid of `cell` pixels, per brightness band, so a backdrop continues the backdrop and not
    the lit floor below it, with `push_pull`. Where the fill is flat and close to that estimate, the difference goes, low
    frequencies only. Where they differ a lot (an edge, a revealed object) or the fill is textured, nothing changes. The
    imprint of the removed object goes one way only: a bright object leaves a pale shape (darkened), a dark one a smudge
    (lightened).

    fill and base: (H, W, 3 or 4) floats 0..1, the fill and the frame under it; alpha (H, W): where the fill covers;
    paint (H, W): where the object was (alpha when None). Levels are 0 to 255.
    """
    H, W = fill.shape[:2]
    h, w = -(-H // cell), -(-W // cell)

    def cells(x):  # sums per cell of the grid
        x = np.pad(x, ((0, h * cell - H), (0, w * cell - W)) + ((0, 0),) * (x.ndim - 2))
        return x.reshape(h, cell, w, cell, *x.shape[2:]).sum((1, 3))

    luma = np.array([0.2126, 0.7152, 0.0722])
    f = fill[..., :3].astype(np.float64) * 255.0
    a = np.clip(alpha.astype(np.float64), 0.0, 1.0)
    p = a if paint is None else np.clip(paint.astype(np.float64), 0.0, 1.0)
    count, sa = cells(np.ones((H, W))), cells(a)
    known = cells(p) <= 0.01 * count  # cells the object never touched: the frame there is the background
    if not known.any():
        return fill.copy(), 0.0
    mean = cells(base[..., :3].astype(np.float64) * 255.0) / count[..., None]
    lit = f @ luma
    safe = np.maximum(sa, 1e-9)
    fmean = cells(a[..., None] * f) / safe[..., None]
    lmean, lfill = mean @ luma, fmean @ luma
    bands = (2.5, 4.0, 5.5, 7.0, 8.5)  # log2(level + 4): shadows to highlights

    def member(level, k):
        return np.maximum(0.0, 1.0 - np.abs(np.log2(np.maximum(0.0, level) + 4.0) - bands[k]) / 1.5)

    unknown = ~known & (sa > 0)
    total, weight = np.zeros_like(mean), np.zeros((h, w))
    for k in range(len(bands)):
        wk = np.where(known, member(lmean, k), 0.0)
        if not (wk > 0.05).any():
            continue
        estimate = push_pull(np.where(known[..., None], mean, 0.0), wk)
        mk = np.where(unknown, member(lfill, k), 0.0)
        total, weight = total + mk[..., None] * estimate, weight + mk
    # nothing as bright around it: the fill is its own background, and stays as it is
    bg = np.where(unknown[..., None], np.where(weight[..., None] > 0, total / np.maximum(weight, 1e-9)[..., None], fmean), mean)
    d = bg - fmean
    level = cells(a * lit) / safe
    std = np.sqrt(np.maximum(0.0, cells(a * lit * lit) / safe - level * level))
    dl = d @ luma
    removed = np.where(known, 0.0, lmean - bg @ luma)  # the object's brightness against the background
    along = np.where(removed > 2, dl < 0, np.where(removed < -2, dl > 0, True))
    covers = sa > 0
    corr = np.where((along & covers)[..., None], d * (_ramp(np.abs(dl), *near) * _ramp(std, *flat))[..., None], 0.0)
    num, den = corr, covers.astype(np.float64)
    for _ in range(2):  # a soft correction that keeps its value up to the edge of the fill
        for axis in (1, 0):
            num, den = _box3(num, axis), _box3(den, axis)
    corr = np.where((covers & (den > 0))[..., None], num / np.maximum(den, 1e-9)[..., None], 0.0)
    gy = np.clip((np.arange(H) + 0.5) / cell - 0.5, 0, h - 1)
    gx = np.clip((np.arange(W) + 0.5) / cell - 0.5, 0, w - 1)
    y0, x0 = np.floor(gy).astype(int), np.floor(gx).astype(int)
    y1, x1 = np.minimum(h - 1, y0 + 1), np.minimum(w - 1, x0 + 1)
    ty, tx = (gy - y0)[:, None, None], (gx - x0)[None, :, None]
    v = (corr[y0][:, x0] * (1 - tx) + corr[y0][:, x1] * tx) * (1 - ty) + (corr[y1][:, x0] * (1 - tx) + corr[y1][:, x1] * tx) * ty
    inside = a > 0
    out = fill.astype(np.float32).copy()
    out[..., :3] = np.where(inside[..., None], np.clip(f + v, 0.0, 255.0), f) / 255.0
    moved = float(np.abs(v @ luma)[inside].mean()) if inside.any() else 0.0
    return out, moved


def steady_masks(masks: np.ndarray, radius: int, grow: float, feather: float) -> np.ndarray:
    """Masks (N, H, W) whose edge moves smoothly from frame to frame.

    Each frame takes the widest coverage of its neighbours within `radius` frames, grows by
    `grow` pixels, is averaged over the same neighbours, then softened by `feather` pixels.
    A tracker's edge that changes every frame becomes one steady, soft edge.
    """
    m = np.clip(masks.astype(np.float32), 0.0, 1.0)
    span = 2 * radius + 1
    if radius > 0 and len(m) > 1:
        m = ndimage.maximum_filter1d(m, span, axis=0, mode="nearest")
    if grow > 0:
        m = dilate(m, grow)
    if radius > 0 and len(m) > 1:
        m = ndimage.uniform_filter1d(m, span, axis=0, mode="nearest")
    if feather > 0:
        m = ndimage.gaussian_filter(m, (0, feather / 2.0, feather / 2.0))
    return np.clip(m, 0.0, 1.0)


def dilate(m: np.ndarray, grow: float) -> np.ndarray:
    """Grow a mask (or a stack of masks) by `grow` pixels: two running maxima, along rows then columns.

    As fast at 60 px as at 6; the square corners it leaves are rounded by the feather that follows.
    """
    size = 2 * int(np.ceil(grow)) + 1
    return ndimage.maximum_filter1d(ndimage.maximum_filter1d(m, size, axis=-1, mode="nearest"), size, axis=-2, mode="nearest")


def smooth_track(track: np.ndarray, radius: int) -> np.ndarray:
    """A per-frame measurement (N, K) made steady: the median over 2r+1 frames, then their mean."""
    track = np.asarray(track, np.float64)
    if radius <= 0 or len(track) < 3:
        return track
    t = ndimage.median_filter(track, size=(2 * radius + 1, 1), mode="nearest")
    return ndimage.uniform_filter1d(t, 2 * radius + 1, axis=0, mode="nearest")


def seam_field(plate: np.ndarray, gen: np.ndarray, mask: np.ndarray, band: float) -> np.ndarray:
    """Log ratio (H, W, 3) that brings `gen` to the colour and exposure of `plate` at the edge of `mask`.

    It is measured on a ring just outside the mask, where the composite shows the plate, and
    spread smoothly inside it, as a Poisson blend would: colour and exposure drift are fixed,
    texture is left alone. Work at low resolution: the field is smooth by design.
    """
    outside = mask < 0.02
    if outside.all() or not outside.any():
        return np.zeros(plate.shape[:2] + (3,), np.float32)
    ring = outside & (ndimage.distance_transform_edt(outside) <= band)
    if ring.sum() < 16:
        return np.zeros(plate.shape[:2] + (3,), np.float32)
    d = np.log(np.maximum(plate[..., :3], 1e-4)) - np.log(np.maximum(gen[..., :3], 1e-4))
    lo, hi = np.percentile(d[ring], [10, 90], axis=0)  # another object crossing the ring must not pull the field
    field = push_pull(np.clip(d, lo, hi).astype(np.float32), ring.astype(np.float32))
    field = ndimage.gaussian_filter(field, (band / 2.0, band / 2.0, 0))
    return np.clip(field, -0.4, 0.4).astype(np.float32)


def kept_edges(plate: np.ndarray, gen: np.ndarray, level: float = 0.06) -> np.ndarray:
    """Where the plate and the generated frame both have an edge (H, W): the outline of what stays, a person beside a
    cleaned object, a window frame. An edge only the plate has (the object a Clean removed) is not one."""
    def edges(img):
        y = img[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        return np.hypot(ndimage.sobel(y, 0), ndimage.sobel(y, 1)) / 8.0 > level
    return ndimage.binary_dilation(edges(plate) & edges(gen))  # one pixel wider: a diagonal step cannot slip through


def edge_grow(mask: np.ndarray, stop: np.ndarray, steps: float) -> np.ndarray:
    """`mask` grown by `steps` pixels, one at a time, never into `stop`: a Clean's margin stops at what stays."""
    steps = int(round(steps))
    if steps < 1:
        return mask
    return np.maximum(ndimage.binary_dilation(mask > 0.5, iterations=steps, mask=~stop).astype(np.float32), mask)


def fit_to_plate(n, h, w, plate_at, gen_at, masks, *, align=True, max_shift=8.0, match_color=True, grain=1.0,
                 grow=8, feather=12, steady=2, workers=8, progress=None, keep=None):
    """Fit `n` generated frames to the plate they are composited onto. Returns (images, masks), full size.

    `plate_at(i)` gives frame i as an (h, w, C) float array; `gen_at(i)` gives it at the plate's size or smaller (a shot
    made at the working size of a 4K plate): then only the window around the matte is enlarged, with a Lanczos-3
    (`resize_lanczos`), frame by frame. `masks` is (N or 1, any height, any width). The mask edge, the shift and the colour match are smoothed over
    `steady` frames on each side, so nothing in the composite changes from one frame to the next unless
    the shot does. Masks and colour fields are computed at about 480 px, alignment at about 512 px. `keep` (N or 1, any
    size), optional: where the shot keeps its own colours, a painted object. The colour match then fixes only the edge the
    composite adds around it, and any other area of the matte (a cleaned one), so a painted object keeps its colours.
    """
    if os.environ.get("PAINTAPLATE_RECORD"):  # what the composite was given (record_fit): tests/matte_study.py reads it
        record_fit(os.environ["PAINTAPLATE_RECORD"], n, plate_at, gen_at, masks, keep, {"align": align, "max_shift": max_shift,
                   "match_color": match_color, "grain": grain, "grow": grow, "feather": feather, "steady": steady})
    tick = progress or (lambda: None)

    def full(g):  # a frame at the plate's size
        return g if g.shape[:2] == (h, w) else resize_lanczos(g, h, w)
    lo = max(1, round(max(h, w) / MASK_SIDE))
    al = max(1, round(max(h, w) / ALIGN_SIDE))
    hl, wl = max(1, h // lo), max(1, w // lo)
    masks = np.asarray(masks, np.float32)[:n]
    if len(masks) < n:  # a shorter matte holds its last frame
        masks = np.concatenate([masks, np.repeat(masks[-1:], n - len(masks), 0)])
    small = np.stack([resize_to(m, hl, wl) for m in masks])
    def low(g, factor, hh, ww):  # a frame at low resolution: shrunk if it has the plate's size, else resized from its own
        return shrink(g, factor) if g.shape[:2] == (h, w) else resize_lanczos(g, hh, ww)

    kept = painted = None
    if keep is not None:  # a painted object: the colour field leaves it as the shot made it, steady from frame to frame
        keep = np.asarray(keep, np.float32)[:n]
        if len(keep) < n:
            keep = np.concatenate([keep, np.repeat(keep[-1:], n - len(keep), 0)])
        painted = np.stack([resize_to(m, hl, wl) for m in keep])
        kept = steady_masks(painted, steady, 0.0, max(1.0, feather / lo / 2))
    cleaned = small if painted is None else np.clip(small - painted, 0.0, 1.0)  # the part of the matte that a Clean regenerates
    if cleaned.max() > 0.02 and grow > feather:  # a Clean's wide margin: all of the object, its soft edges and what it blurs
        near = dilate(cleaned, feather / lo)  # its first stretch, as wide as the feather, always grows: the object's rim and outline go whole

        def margin(i):  # the rest stops at the edges the plate and the clean plate both keep, the outline of what stays; its soft edge too
            stop = kept_edges(low(plate_at(i), lo, hl, wl), low(gen_at(i), lo, hl, wl))
            grown = edge_grow(near[i], stop, (grow - feather) / lo)
            return grown, edge_grow(grown, stop, 2 * feather / lo)
        with ThreadPoolExecutor(workers) as pool:
            grown, limits = (np.stack(part) for part in zip(*pool.map(margin, range(n))))
        small = np.maximum(steady_masks(near, steady, 0.0, feather / lo), steady_masks(grown, steady, 0.0, feather / lo) * limits)
        if painted is not None:
            small = np.maximum(small, steady_masks(painted, steady, grow / lo, feather / lo))
    else:
        small = steady_masks(small, steady, grow / lo, feather / lo)
    band = max(4.0, (grow + feather) / lo)
    ha, wa = max(1, h // al), max(1, w // al)

    def measure(i):  # pass 1: the shift and the colour field of one frame, at low resolution
        p, g = plate_at(i), gen_at(i)
        dy = dx = 0.0
        if align:
            plain = 1.0 - resize_to(small[i], ha, wa)  # where the composite shows the plate: the two frames are compared there
            dy, dx = phase_shift(structure(shrink(p, al)) * plain, structure(low(g, al, ha, wa)) * plain, max_shift / al, fine=True)
            dy, dx = dy * al, dx * al
        field = None
        if match_color and small[i].max() > 0.02:
            gl = low(g, lo, hl, wl)
            if dy or dx:
                gl = ndimage.shift(gl, (dy / lo, dx / lo, 0), order=1, mode="nearest")
            field = seam_field(shrink(p, lo), gl, small[i], band)
        tick()
        return (dy, dx), field

    with ThreadPoolExecutor(workers) as pool:  # numpy and scipy release the GIL
        measured = list(pool.map(measure, range(n)))
    shifts = smooth_track(np.array([s for s, _ in measured]), steady + 1)
    fields = None
    if any(f is not None for _, f in measured):
        stack = np.stack([np.zeros((hl, wl, 3), np.float32) if f is None else f for _, f in measured])
        fields = ndimage.uniform_filter1d(stack, 2 * steady + 1, axis=0, mode="nearest") if steady else stack
    level = np.zeros(3, np.float32)
    if grain > 0:  # one grain level for the whole shot: the plate's grain minus what the generation already has
        picks = list(range(0, n, max(1, n // 3)))[:3]
        target = np.median([noise_sigma(plate_at(i)) for i in picks], 0)
        own = np.median([noise_sigma(full(gen_at(i))) for i in picks], 0)
        level = np.sqrt(np.maximum(target ** 2 - own ** 2, 0.0)) * grain

    def apply(i):  # pass 2: full size, only around the edit
        g = gen_at(i)
        dy, dx = shifts[i]
        m = resize_to(small[i], h, w)
        ys, xs = np.nonzero(m > 1.0 / 1024)
        if g.shape[:2] != (h, w):  # smaller: the window around the matte enlarged, the rest left black (the composite takes the plate there)
            pad = int(np.ceil(max(abs(dy), abs(dx)))) + 2
            big = np.zeros((h, w, g.shape[2]), np.float32)
            if len(ys):
                wy0, wy1 = max(0, ys.min() - pad), min(h, ys.max() + 1 + pad)
                wx0, wx1 = max(0, xs.min() - pad), min(w, xs.max() + 1 + pad)
                big[wy0:wy1, wx0:wx1] = resize_lanczos(g, h, w, (wy0, wy1, wx0, wx1))
            g = big
        if abs(dy) > 0.05 or abs(dx) > 0.05:
            g = ndimage.shift(g, (dy, dx, 0), order=1, mode="nearest")
        g = np.array(g, np.float32, copy=True)
        if len(ys):
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            if fields is not None:  # the colour field, enlarged like the mask; none on a painted object (keep)
                f = resize_to(fields[i], h, w)[y0:y1, x0:x1]
                if kept is not None:
                    f = f * (1.0 - np.clip(resize_to(kept[i], h, w)[y0:y1, x0:x1], 0.0, 1.0))[..., None]
                g[y0:y1, x0:x1, :3] *= np.exp(f)
            if np.any(level > 0):
                g[y0:y1, x0:x1] = add_grain_level(g[y0:y1, x0:x1], level, np.random.default_rng(i))
        tick()
        return g, m.astype(np.float32)

    with ThreadPoolExecutor(workers) as pool:
        done = list(pool.map(apply, range(n)))
    return [d[0] for d in done], [d[1] for d in done]


def keyframe_video(keys, width: int, height: int, frames: int, read) -> np.ndarray:
    """A control video (frames, height, width, 3): black, with each key's image at its frame.

    `keys` is a list of {"frame": n, "image": name} and `read(name)` returns that image as (height, width, 3) floats.
    A frame outside the clip is clamped to it; of two keys on one frame, the later wins. ainvfx-fluid reads keyframes
    painted in flat colours this way: on frame 0, on the last frame, and on the 8k + 1 frames between.
    """
    video = np.zeros((frames, height, width, 3), np.float32)
    for key in keys:
        video[min(max(int(key["frame"]), 0), frames - 1)] = np.asarray(read(key["image"]), np.float32)[:height, :width, :3]
    return video


# Relight Transfer. The regenerated frame brings the new light; the plate keeps its fine detail and its own values.
# The change of light is the log of the frame's luminance over the plate's, smoothed by a Gaussian of `radius` pixels, plus
# the change of each channel's share of the luminance, smoothed over LIGHT_COLOUR_SPREAD radii, with a channel never counted
# below CHANNEL_FLOOR of the luminance, so a dark channel cannot swing the colour. The filters are fixed: nothing depends on
# a frame's own figures, so a steady shot gives a steady result (an edge-aware filter, or gains anchored on each
# frame, makes a steady full-size shot flicker).
LIGHT_EPS = 1.0 / 512.0  # linear light: darker than this counts as this dark when the change is measured
LIGHT_COLOUR_SPREAD = 4.0
CHANNEL_FLOOR = 0.1
RATIO_RANGE = (1.0 / 64.0, 64.0)  # a safety net, not a limit: a painted sun can be 30 times the sky it covers


def light_change(source: np.ndarray, relit: np.ndarray, radius: float) -> np.ndarray:
    """The change of light from `source` to `relit` (H, W, 3), both linear light at the same size, in natural log."""
    src, rel = source[..., :3].clip(0), relit[..., :3].clip(0)
    ys, yr = luma(src)[..., None], luma(rel)[..., None]
    bright = ndimage.gaussian_filter(np.log(yr + LIGHT_EPS) - np.log(ys + LIGHT_EPS), (radius, radius, 0))
    share = lambda c, y: np.log((c + CHANNEL_FLOOR * y + LIGHT_EPS) / ((1.0 + CHANNEL_FLOOR) * y + LIGHT_EPS))
    spread = LIGHT_COLOUR_SPREAD * radius
    colour = ndimage.gaussian_filter(share(rel, yr) - share(src, ys), (spread, spread, 0))
    return (bright + colour).astype(np.float32)


def light_ratio(source: np.ndarray, relit: np.ndarray, radius: float) -> np.ndarray:
    """The change of light (`light_change`) as a ratio per channel, within RATIO_RANGE."""
    return np.exp(np.clip(light_change(source, relit, radius), np.log(RATIO_RANGE[0]), np.log(RATIO_RANGE[1]))).astype(np.float32)


def relight(plate: np.ndarray, source: np.ndarray, relit: np.ndarray, radius: float, strength: float = 1.0) -> np.ndarray:
    """Move the light of `relit` onto `plate`, keeping the plate's own detail.

    All three images are linear light. `source` and `relit` share the working size; `plate` can be larger. The change
    of light (`light_ratio`) multiplies the plate, so its texture, grain and values above 1.0 stay its own.
    """
    ratio = light_ratio(source, relit, radius) ** strength
    if ratio.shape[:2] != plate.shape[:2]:
        ratio = resize_to(ratio, plate.shape[0], plate.shape[1])
    out = plate.copy()
    out[..., :3] = plate[..., :3] * ratio
    return out


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    """The sRGB transfer function, decoded (IEC 61966-2-1): display values to linear light."""
    x = np.asarray(x, np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((np.maximum(x, 0.04045) + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """The sRGB transfer function, encoded: linear light to display values. Values above 1.0 stay above 1.0."""
    x = np.asarray(x, np.float32)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.maximum(x, 0.0031308) ** (1 / 2.4) - 0.055).astype(np.float32)


def frame_shift(source: np.ndarray, relit: np.ndarray, plate_width: int, shot_space: str = "linear"):
    """How far `relit` sits from `source`, as the (dy, dx) that moves it back, in pixels of `source`: phase correlation of
    their structure, up to 8 plate pixels."""
    if shot_space == "sRGB":
        source, relit = srgb_to_linear(source[..., :3]), srgb_to_linear(relit[..., :3])
    return phase_shift(structure(source), structure(relit), 8.0 * source.shape[1] / plate_width, fine=True)


def shot_shift(shifts) -> tuple:
    """One shift for the whole shot: the median of every frame's, so the realignment never moves from frame to frame."""
    s = np.asarray(shifts, np.float64).reshape(-1, 2)
    return (float(np.median(s[:, 0])), float(np.median(s[:, 1]))) if len(s) else (0.0, 0.0)


def relight_frame(plate: np.ndarray, source: np.ndarray, relit: np.ndarray, radius: float, strength: float = 1.0,
                  shift=(0.0, 0.0), plate_space: str = "linear", shot_space: str = "linear") -> np.ndarray:
    """One frame of Relight Transfer: `relit` moved by `shift` onto `source`, then its light moved onto `plate`.

    The change of light is measured at the size of `source` and `relit`, then enlarged to the plate. The workflows give
    them at half the plate's size, where `radius` 1 still lets the shot's light through almost pixel for pixel.
    """
    if shot_space == "sRGB":  # source and relit as the model saw and made them
        source, relit = srgb_to_linear(source[..., :3]), srgb_to_linear(relit[..., :3])
    dy, dx = shift
    if dy or dx:
        relit = ndimage.shift(relit, (dy, dx, 0), order=1, mode="nearest")
    if plate_space == "sRGB":  # decoded here, frame by frame, then encoded back: far cheaper than core at full size
        plate = np.concatenate([srgb_to_linear(plate[..., :3]), plate[..., 3:]], -1)
    out = relight(plate, source, relit, max(0.5, radius), strength).astype(np.float32)
    if plate_space == "sRGB":
        out[..., :3] = linear_to_srgb(out[..., :3])
    return out


FOLLOW_FLICKER = 3  # frames: a piece of the matte that comes and goes within this many frames is a flicker (matte_flicker)
FOLLOW_SHIFT = 1 / 320  # of the width (2 px at 640): a pixel of the shot within the plate's own range this far around it is no change


def shot_change(shot: np.ndarray, plate: np.ndarray) -> np.ndarray:
    """How far a regenerated frame is from the plate's frame under it, per pixel: (H, W) from two (H, W, 3) frames in
    0 to 1. Each pixel counts from the plate's own range of values FOLLOW_SHIFT of the width around it, so a road that
    the shot only shifted is no change, then the result is softened by one pixel. Follow Matte's test of change."""
    size = (2 * max(1, round(FOLLOW_SHIFT * plate.shape[1])) + 1,) * 2 + (1,)
    return ndimage.gaussian_filter(np.maximum(ndimage.minimum_filter(plate, size) - shot, shot - ndimage.maximum_filter(plate, size)).max(axis=-1).clip(0), 1.0)


def reference_frames(n: int) -> list:
    """The frames that a matte's references are drawn on: the first, the last and three between (0, 30, 60, 90 and 120
    of 121 frames). record_fit keeps them at full size."""
    return sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1}) if n > 0 else []


def record_fit(folder: str, n: int, plate_at, gen_at, masks, keep, values: dict) -> str:
    """With PAINTAPLATE_RECORD=<folder> in ComfyUI's environment, what Fit to Plate was given, as one .npz file beside
    Follow Matte's: every frame of the plate and of the generated frames (the shot, or a Clean's clean plate pass) at
    the matte's size, the frames of reference_frames at their own sizes, the mattes and `keep` as given, in half floats,
    and the node's values. A Clean's clean plate pass is recorded nowhere else. replay_fit reads it back. Returns the
    file's path."""
    m = np.asarray(masks, np.float32)
    mh, mw = m.shape[-2:]
    h, w = np.shape(plate_at(0))[:2]

    def small(f):  # a frame at the matte's size: whole blocks averaged, then resampled
        f = np.asarray(f, np.float32)[..., :3]
        return resize_to(shrink(f, max(1, min(f.shape[0] // mh, f.shape[1] // mw))), mh, mw).astype(np.float16)

    whole = lambda f: np.asarray(f, np.float32)[..., :3].astype(np.float16)  # noqa: E731
    pick = reference_frames(n)
    names = sorted(values)
    os.makedirs(folder, exist_ok=True)
    stamp = f"{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}"
    path = os.path.join(folder, f"fit_to_plate_{w}x{h}_{n}f_{stamp}.npz")
    np.savez_compressed(path, plate=np.stack([small(plate_at(t)) for t in range(n)]), image=np.stack([small(gen_at(t)) for t in range(n)]),
                        spread_plate=np.stack([whole(plate_at(t)) for t in pick]), spread_image=np.stack([whole(gen_at(t)) for t in pick]),
                        masks=m.astype(np.float16), keep=np.zeros((0,), np.float16) if keep is None else np.asarray(keep, np.float16),
                        pick=np.array(pick), names=np.array(names), values=np.array([float(values[k]) for k in names]), n=n)
    return path


def replay_fit(path: str) -> dict:
    """What record_fit wrote, in floats: `plate` and `image` (N, h, w, 3) at the matte's size, `spread_plate` and
    `spread_image` on the frames of `pick`, `masks`, `keep` (or None) and the node's `values` by name. An array kept in
    8 bits, as in a smaller copy of the file, reads from 0 to 1, as in replay."""
    d = np.load(path)
    f = lambda k: d[k].astype(np.float32) / (255.0 if d[k].dtype == np.uint8 else 1.0)  # noqa: E731
    return {"n": int(d["n"]), "plate": f("plate"), "image": f("image"), "spread_plate": f("spread_plate"), "spread_image": f("spread_image"),
            "masks": f("masks"), "keep": f("keep") if d["keep"].size else None, "pick": [int(t) for t in d["pick"]],
            "values": {str(k): float(v) for k, v in zip(d["names"], d["values"])}}


def matte_flicker(mattes, run: int = 3) -> np.ndarray:
    """How much a matte flickers, frame by frame (a detection per frame can lose an arm on 18
    of 121 frames): the share of the matte that appears or disappears for `run` frames at most, then comes back as it was.
    A piece counts on frames s to s+L-1 (L <= run) when frames s-1 and s+L agree on it and every frame between differs,
    and when it reaches more than (L+1) * r px inside both, or outside both, with r = max(1, W / 240): a move of r px a
    frame does not count. The value on a frame is the pieces' area against the largest matte of frames s-1 to s+L. A
    matte that comes or goes for good (the object hidden, back, or gone) does not count."""
    M = np.asarray(mattes) > 0.5
    n, w = len(M), M.shape[-1]
    r, area, out = max(1, round(w / 240)), M.reshape(n, -1).sum(1), np.zeros(n)

    def whole(piece, seed):  # the pieces that reach the seed, whole
        labels, _ = ndimage.label(piece)
        ids = np.unique(labels[piece & seed])
        return int(np.isin(labels, ids[ids > 0]).sum())
    for run_ in range(1, run + 1):
        for s in range(1, n - run_):
            before, after, between = M[s - 1], M[s + run_], M[s:s + run_]
            lost, extra, k = before & after & ~between.any(0), ~before & ~after & between.all(0), 0
            if lost.any():
                k += whole(lost, ndimage.binary_erosion(before & after, iterations=(run_ + 1) * r))
            if extra.any():
                k += whole(extra, ~ndimage.binary_dilation(before | after, iterations=(run_ + 1) * r))
            if k:
                out[s:s + run_] = np.maximum(out[s:s + run_], k / max(int(area[s - 1:s + run_ + 1].max()), 1))
    return out


VOTES_ALONE = 0.3  # of a SAM mask's piece: changed by a quarter of the threshold over this share, it is the edit, whole
VOTES_KEPT = 0.5  # of a piece, or of a kept thing: this share on what the plate keeps, or in the element, decides
VOTES_GLOW = 1 / 160  # of the width: what the shot changed this close to the matte joins it, on that frame only
VOTES_PATIENCE = 2  # empty frames in a row before the object counts as hidden or gone
VOTES_SUBJECT = 0.75  # of a kept thing on its first frame: this share in the area the edit works on makes it the edit's subject


def _first_present(m) -> int:
    seen = np.flatnonzero(np.asarray(m).reshape(len(m), -1).any(axis=1))
    return int(seen[0]) if len(seen) else -1


def _edge(m) -> bool:
    return bool(m[:2].any() or m[-2:].any() or m[:, :2].any() or m[:, -2:].any())


def _close(m, r):
    r = int(r)
    return ndimage.binary_closing(np.pad(m, r), iterations=r)[r:-r, r:-r] if r > 0 and m.any() else m


def kept_things(objects, region) -> np.ndarray:
    """What the plate keeps, (N, H, W) booleans from SAM's objects (N, K, H, W): each object, unless on its first frame
    VOTES_SUBJECT of it or more lies in `region`, the area the edit works on: there it is the edit's own subject (a barn
    that a Clean removes, a horse that a paint turns into a robot), not a thing to keep. A horse with a paint on its
    belly lies about half in it, and stays a thing to keep: the matte then cuts SAM's whole horse to the change."""
    objects = np.asarray(objects) > 0.5
    if objects.ndim == 3:  # one thing, (N, H, W)
        objects = objects[:, None]
    out = np.zeros((objects.shape[0],) + objects.shape[2:], bool)
    for k in range(objects.shape[1]):
        m = objects[:, k]
        f0 = _first_present(m)
        if f0 >= 0 and (m[f0] & region).sum() < VOTES_SUBJECT * m[f0].sum():
            out |= m
    return out


def follow_votes(shot_masks, word_masks, plate_masks, kept, element, shot, base, threshold: float = 0.1,
                 zone: float = 1 / 16, first_frame: int = 1, tick=None):
    if os.environ.get("PAINTAPLATE_RECORD"):
        record_votes(os.environ["PAINTAPLATE_RECORD"], "paint", shot_masks=shot_masks, word_masks=word_masks, plate_masks=plate_masks,
                     kept=kept, element=element, shot=shot, base=base, threshold=threshold, zone=zone, first_frame=first_frame)
    return _follow_votes(shot_masks, word_masks, plate_masks, kept, element, shot, base, threshold, zone, first_frame, tick)


def _follow_votes(shot_masks, word_masks, plate_masks, kept, element, shot, base, threshold, zone, first_frame, tick):
    """A paint's matte from SAM 3.1's answers, judged by how much the shot changed (votes). Returns (mattes, summary).

    `shot_masks` and `word_masks` are SAM's masks on the shot (N, H, W), given the element with the object's name and
    the name alone; `plate_masks` its masks on the plate given the element (the object the edit replaces); `kept` what
    the plate keeps (SAM's objects (N, K, H, W), or one (N, H, W), filtered by kept_things against the element closed by
    1/60 of the width); `element` where the edit changed the first frame; `shot` and `base` the
    shot and the plate (N, H, W, 3) in 0 to 1. On the first frame a mask given the element answers with it: the second
    frame's stands in for it. Each piece of the masks is then judged on its frame:
    - a piece that lies mostly on what the plate keeps is cut to the change, closed by 1/320 of the width: a whole horse
      for a paint on its belly keeps the painted part, a patch on a large kept thing stays whole; a cut under 2% of the
      piece is that thing regenerated, and is left out;
    - any other piece is the edit, whole, when the shot changed it by a quarter of the threshold over VOTES_ALONE of it
      (thin smoke changes the plate by a few percent), else it is cut to the change;
    - the plate's masks join where the shot changed, near the shot's masks: the old object, which the new one covers.
    The matte then follows a state. Present, it takes the pieces that lie at least half within the last matte grown by
    `zone` of the width (a mask can jump onto a far thing in the frame its object leaves: a boat's wake). Hidden (it
    vanished inside the frame for VOTES_PATIENCE frames), it takes pieces within the last matte grown by one more zone per
    frame, never one that lies mostly on what the plate keeps. Gone (it vanished after touching the frame's edge), it
    takes nothing. On each frame alone, what the shot changed above the threshold within VOTES_GLOW of the width of the
    matte joins it (a beam's glow, a wing's blur), so it cannot creep. What the plate keeps wins wherever the shot did
    not change. Frames are named by the plate's numbers: `first_frame` is the first one's."""
    n = len(shot)
    h, w = shot.shape[1:3]
    tick = tick or (lambda: None)
    frames = lambda a: np.asarray(a, np.float32)[:n] > 0.5 if a is not None and np.size(a) else np.zeros((n, h, w), bool)  # noqa: E731
    shot_m, word_m, plate_m = frames(shot_masks), frames(word_masks), frames(plate_masks)
    if n > 1:
        shot_m[0] = shot_m[1]
    union = shot_m | word_m
    seed = np.asarray(element, np.float32).reshape(-1, h, w)[0] > 0.5 if element is not None and np.size(element) else np.zeros((h, w), bool)
    seed = _close(seed, max(2, round(w / 60)))
    kept = kept_things(np.asarray(kept, np.float32)[:n], seed) if kept is not None and np.size(kept) else np.zeros((n, h, w), bool)
    reach, near, close = max(2.0, zone * w), max(1.0, w * VOTES_GLOW), max(1, round(w / 320))
    grow = lambda m, px: dilate(m.astype(np.uint8), px) > 0 if m.any() else m  # noqa: E731
    out = np.zeros((n, h, w), np.float32)
    state, prev, hidden_for, empty = "present", np.zeros((h, w), bool), 0, 0
    counts = dict(old=0, cut=0, away=0, added=0, kept=0)
    hidden, gone_at = [], None
    with ThreadPoolExecutor(min(16, os.cpu_count() or 4)) as pool:  # each frame's change on its own: scipy's filters release the GIL
        diffs = list(pool.map(lambda t: shot_change(shot[t], base[t]), range(n)))
    for t in range(n):
        d = diffs[t]
        away_from = ~grow(union[t] | plate_m[t], reach)
        level = float(np.median(d[away_from])) if away_from.sum() > 256 else float(np.median(d))
        changed, moved = d > level + threshold, d > level + 0.25 * threshold
        labels, count = ndimage.label(union[t])
        cand, cut = np.zeros((h, w), bool), np.zeros((h, w), bool)
        for k in range(1, count + 1):
            piece = labels == k
            if (piece & kept[t]).sum() >= VOTES_KEPT * piece.sum():
                c = piece & grow(changed, 2)
                if c.sum() >= 0.02 * piece.sum():  # less is the kept thing regenerated: specks
                    cut |= c
            elif moved[piece].mean() >= VOTES_ALONE:
                cand |= piece
            else:
                cut |= piece & grow(changed, 2)
        counts["cut"] += bool(cut.any())
        cand |= _close(cut, close)
        old = plate_m[t] & grow(changed, 2)
        if old.any():
            ol, _ = ndimage.label(old)
            hit = np.unique(ol[old & grow(union[t], reach)])
            old = np.isin(ol, hit[hit > 0])
            counts["old"] += bool(old.any())
        cand = ndimage.binary_fill_holes(cand | old)
        if t == 0:
            allowed = grow(seed, reach) if seed.any() else np.ones((h, w), bool)
        elif state == "present":
            allowed = grow(prev, reach)
        elif state == "hidden":
            allowed = grow(prev, reach * (1 + hidden_for))
        else:
            allowed = np.zeros((h, w), bool)
        labels, count = ndimage.label(cand)
        m = np.zeros((h, w), bool)
        left_out = False
        for k in range(1, count + 1):
            piece = labels == k
            if (piece & allowed).sum() < 0.5 * piece.sum() or (state == "hidden" and (piece & kept[t]).sum() >= VOTES_KEPT * piece.sum()):
                left_out = True
                continue
            m |= piece
        counts["away"] += left_out
        if m.any():
            glow = changed & grow(m, near) & ~m
            counts["added"] += bool(glow.any())
            m |= glow
            if state == "hidden" and hidden and hidden[-1][1] is None:
                hidden[-1][1] = t - 1
            state, prev, hidden_for, empty = "present", m, 0, 0
        else:
            empty += 1
            if state == "present" and t > 0 and empty >= VOTES_PATIENCE:
                if _edge(prev):
                    state, gone_at = "gone", t - empty + 1
                else:
                    state, hidden_for = "hidden", 1
                    hidden.append([t - empty + 1, None])
            elif state == "hidden":
                hidden_for += 1
        dropped = m & kept[t] & ~moved
        counts["kept"] += bool(dropped.any())
        out[t] = m & ~dropped
        tick()
    if hidden and hidden[-1][1] is None:
        hidden[-1][1] = n - 1
    flicker = matte_flicker(out)
    worst = int(np.argmax(flicker)) if len(flicker) else 0
    return out, votes_summary(n, int(union.reshape(n, -1).any(axis=1).sum()), counts, hidden, gone_at,
                              (int((flicker > 0).sum()), float(flicker.max()) if len(flicker) else 0.0, worst), first_frame)


SAM_WORDS_CUT = (" with ", " in ", " on ", " at ", " from ", " behind ", " outside ", " including ", " that ", " which ", ",",
                 " standing", " landing", " rising", " hanging", " overlapping")


def sam_words(answer: str, kind: str = "thing") -> str:
    """The words SAM 3.1 searches for, from the prompt upsampler's answer. `kind` "thing": the edit's object, a short
    noun phrase: a longer answer keeps its first one (« bald eagle landing on the fence post » gives « bald eagle »).
    "kept": what the plate keeps, the first entry of the list the upsampler gives, its main person, animal or vehicle
    (« person », « horse », « white van »): the entries after it name parts and accessories (« blue-sleeved arm »), which
    the edit may change. Entries of more than four words, denials (« no other people ») and « none » never count.
    Lowercase, without a final full stop."""
    text = " ".join(str(answer or "").strip().strip(".").lower().split())
    if kind == "kept":
        items = [x.strip().strip(".") for x in text.split(",")]
        items = [x for x in items if x and x != "none" and len(x.split()) <= 4 and not x.startswith("no ") and "visible" not in x]
        return items[0] if items else ""
    for word in SAM_WORDS_CUT:
        if word in f" {text} ":
            text = f" {text} ".split(word)[0].strip()
    return text


def clean_votes(zone_masks, named, kept, zone, first_frame: int = 1):
    if os.environ.get("PAINTAPLATE_RECORD"):
        record_votes(os.environ["PAINTAPLATE_RECORD"], "clean", zone_masks=zone_masks, named=named, kept=kept, zone=zone, first_frame=first_frame)
    return _clean_votes(zone_masks, named, kept, zone, first_frame)


def _clean_votes(zone_masks, named, kept, zone, first_frame):
    """A Clean's matte from SAM 3.1's answers on the plate. Returns (mattes, summary). `zone_masks` (N, H, W) is SAM's
    track of the zone; `named` (N, K, H, W) its objects of the removed thing's name, or None; `kept` SAM's objects of what
    the plate keeps (N, K, H, W), filtered by kept_things against the zone, so the removed thing is not among them;
    `zone` (H, W) the painted
    area. On the first frame SAM's track answers with the zone: the named objects that lie mostly in it stand in for
    it. The matte is the track minus what the plate keeps (a person in front of the palm behind her)."""
    m = np.asarray(zone_masks, np.float32) > 0.5
    n = len(m)
    zone = np.asarray(zone, np.float32).reshape(-1, *m.shape[1:])[0] > 0.5
    if named is not None and np.size(named):
        named = np.asarray(named, np.float32) > 0.5
        first = np.zeros(m.shape[1:], bool)
        for k in range(named.shape[1]):
            a = named[0, k]
            if a.any() and (a & zone).sum() >= VOTES_KEPT * a.sum():
                first |= a
        if first.any():
            m[0] = first
    kept = kept_things(np.asarray(kept, np.float32)[:n], zone) if kept is not None and np.size(kept) else np.zeros_like(m)
    out = m & ~kept
    seen = int(m.reshape(n, -1).any(axis=1).sum())
    left = int((m & kept).reshape(n, -1).any(axis=1).sum())
    lines = [f"tracked on {seen} of {n} frames."] + [f"Left out: what the plate keeps (person, animal, vehicle), on {left} frame" + ("" if left == 1 else "s") + "."] * bool(left)
    return out.astype(np.float32), "\n  ".join(lines)


def record_votes(folder: str, kind: str, **arrays) -> str:
    """With PAINTAPLATE_RECORD=<folder>, what Follow Matte was given, as one .npz file: SAM 3.1's answers, the element or
    the zone, the shot and the plate, in half floats, with the values. replay_votes reads it back, so the matte runs
    again on a CPU (tests/matte_study.py). Returns the file's path."""
    os.makedirs(folder, exist_ok=True)
    out = {"kind": np.array(kind)}
    for k, v in arrays.items():
        out[k] = np.zeros((0,), np.float16) if v is None or not np.size(v) else np.asarray(v, np.float32).astype(np.float16)
    first = next((a for a in arrays.values() if a is not None and np.ndim(a) >= 3), None)
    n, h, w = (np.shape(first)[0], np.shape(first)[1], np.shape(first)[2]) if first is not None else (0, 0, 0)
    path = os.path.join(folder, f"follow_votes_{kind}_{w}x{h}_{n}f_{time.strftime('%Y%m%d_%H%M%S')}.npz")
    np.savez_compressed(path, **out)
    return path


def replay_votes(path: str) -> dict:
    """What record_votes wrote: {"kind": "paint" or "clean", "args": the arguments of follow_votes or clean_votes}."""
    d = np.load(path)
    back = lambda k: d[k].astype(np.float32) if d[k].size else None  # noqa: E731
    kind = str(d["kind"])
    scalars = {k: (int(d[k]) if k == "first_frame" else float(d[k])) for k in ("threshold", "zone", "first_frame") if k in d.files and d[k].ndim == 0}
    names = ("shot_masks", "word_masks", "plate_masks", "kept", "element", "shot", "base") if kind == "paint" else ("zone_masks", "named", "kept", "zone")
    args = {k: back(k) for k in names if k in d.files}
    if kind == "clean":
        scalars.pop("threshold", None)
        args["zone"] = back("zone")
    return {"kind": kind, "args": {**args, **scalars}}


def votes_summary(n: int, seen: int, counts: dict, hidden=(), gone_at=None, flicker=None, first_frame: int = 1) -> str:
    """Follow Matte's summary for a person: the headline, then one line per rule that acted, the plate's numbers for
    frames. The page writes « Paint matte (…): » or « Clean matte (…): » before it."""
    on = lambda k: f"{k} frame" + ("" if k == 1 else "s")  # noqa: E731
    lines = [f"tracked on {seen} of {n} frames."]
    if counts.get("old"):
        lines.append(f"Old object added where the shot changed, on {on(counts['old'])}.")
    if counts.get("cut"):
        lines.append(f"Cut to the change: SAM masks over what the plate keeps, on {on(counts['cut'])}.")
    if counts.get("kept"):
        lines.append(f"Left out: what the plate keeps (person, animal, vehicle) where the shot did not change, on {on(counts['kept'])}.")
    if counts.get("away"):
        lines.append(f"Left out: SAM masks away from the object, on {on(counts['away'])}.")
    if counts.get("added"):
        lines.append(f"Added: what the shot changed beside the object, on {on(counts['added'])}.")
    for a, b in hidden:
        lines.append(f"Object hidden from frame {a + first_frame} to {b + first_frame}.")
    if gone_at is not None:
        lines.append(f"Object out of the frame from frame {gone_at + first_frame}.")
    if flicker is not None and flicker[0]:
        share = f"{100 * flicker[1]:.0f}%" if flicker[1] >= 0.1 else f"{100 * flicker[1]:.1f}%"
        lines.append(f"Flicker: pieces of the matte for {FOLLOW_FLICKER} frames or fewer, on {on(flicker[0])} (up to {share} of the matte at frame {flicker[2] + first_frame}).")
    return "\n  ".join(lines)


GRAIN_UNIT = _grain_unit()


# ---------- SDR to HDR: the HDR shot's level fitted to the plate ----------
HDR_FLOOR = 2.0 ** -14  # the smallest normal half float: darker values carry no usable ratio
HDR_MIDTONES = (2.0 ** -6, 2.0 ** -0.5)  # plate luminance where the level is measured: above the noise, below SDR's white
HDR_SPAN = 9  # frames over which each frame's gain is smoothed (smooth_gains)
HDR_FRAME_LEAST = 256  # untouched mid-tone samples a frame needs for a gain of its own


def hdr_level(shot: np.ndarray, plate: np.ndarray, band=HDR_MIDTONES, least: int = 2048):
    """One gain per channel, in stops, that brings the HDR shot's level to the plate's: the median of log2(plate / shot) over
    samples of the same pixels ((K, 3) each) whose plate luminance sits in `band`, the mid-tones, where the SDR the model saw
    was still close to linear. None when fewer than `least` samples qualify. A gain changes no ratio within a channel."""
    ok = np.all(np.isfinite(shot) & np.isfinite(plate) & (shot > HDR_FLOOR) & (plate > HDR_FLOOR), axis=-1)
    lum = plate @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    ok &= (lum >= band[0]) & (lum <= band[1])
    if ok.sum() < least:
        return None
    return np.median(np.log2(plate[ok] / shot[ok]), axis=0)


def apply_level(img: np.ndarray, stops) -> np.ndarray:
    """`img`'s RGB times 2 to the `stops` of each channel; zero, negative and non-finite values become 0. Nothing is
    clipped or compressed: the range above the plate's white stays as SDR to HDR made it, for grading."""
    out = np.array(img[..., :3], np.float32)
    good = np.isfinite(out) & (out > 0)
    return np.where(good, out * np.exp2(np.asarray(stops, np.float32)), 0.0).astype(np.float32)


def smooth_gains(gains: list, span: int = HDR_SPAN) -> list:
    """Each frame's gain (stops per channel) as the value at that frame of a straight line fitted, by least squares, to the
    gains of the frames within span // 2 of it. A line follows a drift to the shot's first and last frames, where a mean
    would lag, and a frame whose own gain is off by noise moves its result by a fraction of that. A frame with no gain of its
    own (None) takes the line of its neighbours; None where no frame in reach has one."""
    n, half, out = len(gains), span // 2, []
    for i in range(n):
        near = [(j - i, gains[j]) for j in range(max(0, i - half), min(n, i + half + 1)) if gains[j] is not None]
        if not near:
            out.append(None)
            continue
        x, y = np.array([d for d, _ in near], np.float64), np.array([g for _, g in near], np.float64)
        out.append(y.mean(axis=0) if len(near) < 2 else np.polyfit(x, y, 1)[1])
    return out


def hdr_match(n: int, shot_at, plate_at, changed_at, *, grow: float = 24.0, step: int = 8, samples: int = 1_500_000,
              workers: int = 8):
    """The HDR shot at the level of the plate it is composited onto: (frames, report).

    SDR to HDR picks its own exposure and white balance, and its level drifts over a shot (0.2 stops over 121 frames of
    horse.mp4), while the plate's untouched pixels hold the scene's real values. Each frame's gain per channel (hdr_level)
    is measured where the edits changed nothing (outside `changed_at(i)`, a mask at any size, grown by `grow` plate pixels),
    on a grid every `step` plate pixels; the mid-tones decide it. The gains are smoothed over HDR_SPAN frames
    (smooth_gains), so the level follows the plate with no flicker, then every pixel of a frame is scaled by its gain. A
    frame with too few untouched mid-tones takes its neighbours' line, or the whole shot's gain. A gain keeps every ratio,
    so new content keeps the range SDR to HDR gave it above the plate's white. Frames may differ in size: samples are taken
    at the same places of each frame. Too few untouched mid-tones over the whole shot (an edit over the whole frame) leave
    the shot as it was made."""
    first = plate_at(0)
    hp, wp = first.shape[:2]
    ys = np.minimum(np.arange(step // 2, hp, step), hp - 1)
    xs = np.minimum(np.arange(step // 2, wp, step), wp - 1)
    cap = max(HDR_FRAME_LEAST, samples // max(1, n))  # samples kept per frame

    def sample(i):
        s, p, m = shot_at(i), plate_at(i), changed_at(i)
        hs, ws = s.shape[:2]
        hm, wm = m.shape[:2]
        near = dilate((m > 0.02).astype(np.float32), grow * hm / hp)
        keep = near[(ys * hm // hp)[:, None], (xs * wm // wp)[None, :]] < 0.5
        a, b = s[(ys * hs // hp)[:, None], (xs * ws // wp)[None, :], :3][keep], p[ys[:, None], xs[None, :], :3][keep]
        pick = np.linspace(0, len(a) - 1, cap).astype(int) if len(a) > cap else slice(None)
        return a[pick], b[pick]

    with ThreadPoolExecutor(max(1, workers)) as pool:  # numpy releases the GIL
        parts = list(pool.map(sample, range(n)))
    shot = np.concatenate([a for a, _ in parts]) if parts else np.zeros((0, 3), np.float32)
    plate = np.concatenate([b for _, b in parts]) if parts else np.zeros((0, 3), np.float32)
    stops = hdr_level(shot, plate)
    if stops is None:
        return [np.array(shot_at(i)[..., :3], np.float32) for i in range(n)], {
            "samples": len(shot), "fitted": False,
            "text": f"HDR shot kept as made.\n  Untouched samples: {len(shot):,}, too few mid-tones to measure."}
    gains = smooth_gains([hdr_level(a, b, least=HDR_FRAME_LEAST) for a, b in parts])
    gains = [stops if g is None else np.asarray(g, np.float32) for g in gains]
    fitted = np.concatenate([apply_level(a, g) for (a, _), g in zip(parts, gains)])
    lum = plate @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    mid = np.all((fitted > HDR_FLOOR) & (plate > HDR_FLOOR), axis=-1) & (lum >= HDR_MIDTONES[0]) & (lum <= HDR_MIDTONES[1])
    error = float(np.median(np.abs(np.log2(fitted[mid] / plate[mid])))) if mid.any() else float("nan")
    with ThreadPoolExecutor(max(1, workers)) as pool:
        frames = list(pool.map(lambda i: apply_level(shot_at(i), gains[i]), range(n)))
    means = [float(np.mean(g)) for g in gains]
    return frames, {"samples": len(shot), "fitted": True, "stops": [float(x) for x in stops], "error": error,
                    "frames": [[float(x) for x in g] for g in gains],
                    "text": f"HDR shot fitted to the plate frame by frame on {len(shot):,} untouched samples, each frame's gain "
                            f"smoothed over {HDR_SPAN} frames.\n  Level change (R, G, B) over the shot: "
                            f"{', '.join(f'{x:+.2f}' for x in stops)} stops; by frame, the mean of R, G and B from "
                            f"{min(means):+.2f} to {max(means):+.2f} stops.\n  Nothing compressed.\n"
                            f"  Median mid-tone error after the fit: {error:.3f} stops."}

AP1_TO_REC709 = np.array([[1.70505, -0.62179, -0.08326], [-0.13026, 1.14080, -0.01055], [-0.02400, -0.12897, 1.15297]], np.float32)


def acescct_preview(codes: np.ndarray) -> np.ndarray:
    """ACEScct codes, as the SDR-to-HDR pass decodes them, as 8-bit sRGB for its live preview: decoded to ACEScg
    (S-2016-001), to linear Rec.709, tone-mapped by Reinhard as LTXVHDRDecodePostprocess's own preview, then the sRGB curve."""
    x = codes.astype(np.float32)
    lin = np.where(x <= 0.155251141552511, (x - 0.0729055341958355) / 10.5402377416545, np.exp2(x * 17.52 - 9.72))
    rgb = np.maximum(lin @ AP1_TO_REC709.T, 0.0)
    t = rgb / (1.0 + rgb)
    out = np.where(t <= 0.0031308, 12.92 * t, 1.055 * np.power(np.maximum(t, 1e-8), 1 / 2.4) - 0.055)
    return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
