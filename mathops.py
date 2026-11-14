"""The numpy maths behind the nodes: fitting generated frames to the plate, filling, relighting.

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
    """Where the SDR shot is black, its own black instead of SDR to HDR's: the IC-LoRA's frames carry noise there (a
    16-bit fluid shot on a blank plate, 2 Nov: 67% of its pixels below 0.01, median 6.6e-4, its channels spread by 41%
    of the luminance), while the shot they come from holds the plate's black. `hdr` and `sdr` in ACEScg, scene-linear:
    below `low` (the SDR shot's luminance) the frame takes the SDR values, above `high` SDR to HDR's, a smooth step
    between; values above 1.0 stay wherever the shot is not black."""
    y = np.asarray(sdr[..., :3], np.float32) @ AP1_LUMA
    t = np.clip((y - low) / max(high - low, 1e-9), 0.0, 1.0)
    w = (t * t * (3.0 - 2.0 * t))[..., None]
    out = np.array(hdr, np.float32, copy=True)
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
    `window`, reading just the source pixels they need. The floor for new content enlarged to a plate's native size
    (Adrien's handover, item 5): no clipping, so values above 1.0 and below 0 stay."""
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

    The same result as scipy's zoom (order 1, grid_mode) and torch's bilinear interpolate without align_corners,
    in a quarter of the time: two gathers and two blends in numpy, no spline machinery. Enlarging the masks and
    colour fields to full size was the composite's largest cost.
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
    then animated into smoke (+4 to +6 levels on a backdrop at 18, 28 Oct). The background inside the fill is estimated
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


def fit_to_plate(n, h, w, plate_at, gen_at, masks, *, align=True, max_shift=8.0, match_color=True, grain=1.0,
                 grow=8, feather=12, steady=2, workers=8, progress=None):
    """Fit `n` generated frames to the plate they are composited onto. Returns (images, masks), full size.

    `plate_at(i)` gives frame i as an (h, w, C) float array; `gen_at(i)` gives it at the plate's size or smaller (a shot
    made at the working size of a 4K plate): then only the window around the matte is enlarged, with a Lanczos-3
    (`resize_lanczos`), frame by frame. `masks` is (N or 1, any height, any width). The mask edge, the shift and the colour match are smoothed over
    `steady` frames on each side, so nothing in the composite changes from one frame to the next unless
    the shot does. Masks and colour fields are computed at about 480 px, alignment at about 512 px.
    """
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
    small = steady_masks(small, steady, grow / lo, feather / lo)
    band = max(4.0, (grow + feather) / lo)
    ha, wa = max(1, h // al), max(1, w // al)

    def low(g, factor, hh, ww):  # a frame at low resolution: shrunk if it has the plate's size, else resized from its own
        return shrink(g, factor) if g.shape[:2] == (h, w) else resize_lanczos(g, hh, ww)

    def measure(i):  # pass 1: the shift and the colour field of one frame, at low resolution
        p, g = plate_at(i), gen_at(i)
        dy = dx = 0.0
        if align:
            keep = 1.0 - resize_to(small[i], ha, wa)
            dy, dx = phase_shift(structure(shrink(p, al)) * keep, structure(low(g, al, ha, wa)) * keep, max_shift / al)
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
            if fields is not None:  # the colour field, enlarged like the mask
                g[y0:y1, x0:x1, :3] *= np.exp(resize_to(fields[i], h, w)[y0:y1, x0:x1])
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


# Relight Transfer (31 Oct). The regenerated frame brings the new light; the plate keeps its fine detail and its own values.
# The change of light is the log of the frame's luminance over the plate's, smoothed by a Gaussian of `radius` pixels, plus
# the change of each channel's share of the luminance, smoothed over LIGHT_COLOUR_SPREAD radii, with a channel never counted
# below CHANNEL_FLOOR of the luminance, so a dark channel cannot swing the colour. The filters are fixed: nothing depends on
# a frame's own figures, so a steady shot gives a steady result (Adrien, 31 Oct: the full-size shot was steady, and the
# composite's edge-aware filter and anchor gains made it flicker).
LIGHT_EPS = 1.0 / 512.0  # linear light: darker than this counts as this dark when the change is measured
LIGHT_COLOUR_SPREAD = 4.0
CHANNEL_FLOOR = 0.1
RATIO_RANGE = (1.0 / 64.0, 64.0)  # a safety net, not a limit: a painted sun can be 30 times the sky it covers
# Where a light stroke is strong, the relit frame keeps at least the plate with that light added, in display values, as the
# brush showed it (Adrien, 31 Oct: the painted sun lost its brightness once made). In full from KEEP_LIGHT_AT of light, one
# stroke's peak; less on a stroke's soft edge. Klein relights the rest of the frame.
KEEP_LIGHT_AT = 0.3


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


def keep_light(out: np.ndarray, plate: np.ndarray, light: np.ndarray) -> np.ndarray:
    """`out`, relit from `plate` (both linear light), raised where a light stroke is strong to the plate with that light
    added, as the brush showed it. `light`: the painted light in display values (sRGB), black where none, any size."""
    light = np.asarray(light, np.float32)[..., :3]
    if light.shape[:2] != out.shape[:2]:
        light = resize_to(light, out.shape[0], out.shape[1])
    shown, under = linear_to_srgb(out[..., :3]), linear_to_srgb(plate[..., :3])
    painted = np.minimum(under + light, np.maximum(under, 1.0))  # the brush adds in display values, up to white
    weight = np.clip(light.max(-1, keepdims=True) / KEEP_LIGHT_AT, 0.0, 1.0)
    out = out.copy()
    out[..., :3] = srgb_to_linear(shown + weight * np.maximum(painted - shown, 0.0))
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
    return phase_shift(structure(source), structure(relit), 8.0 * source.shape[1] / plate_width)


def shot_shift(shifts) -> tuple:
    """One shift for the whole shot: the median of every frame's, so the realignment never moves from frame to frame."""
    s = np.asarray(shifts, np.float64).reshape(-1, 2)
    return (float(np.median(s[:, 0])), float(np.median(s[:, 1]))) if len(s) else (0.0, 0.0)


def shade_frame(img: np.ndarray, shade: np.ndarray, density: float = 0.7, space: str = "linear") -> np.ndarray:
    """Darkens a frame where its shade is painted, in linear light, as a compositor multiplies a shadow: `shade` is white
    where the shadow is full (its soft edge as painted), `density` how much light it takes away there. Klein ignores a
    painted shadow (3 Nov test), so a light edit's shade strokes come through here, exactly where they are painted."""
    m = np.asarray(shade, np.float32)
    m = m.mean(-1) if m.ndim == 3 else m
    if m.shape != img.shape[:2]:
        from PIL import Image
        m = np.asarray(Image.fromarray(np.clip(m * 255, 0, 255).astype(np.uint8)).resize((img.shape[1], img.shape[0]), Image.BILINEAR), np.float32) / 255
    k = (1 - np.clip(density, 0, 1) * np.clip(m, 0, 1))[..., None]
    rgb = img[..., :3]
    out = linear_to_srgb(srgb_to_linear(rgb) * k) if space == "sRGB" else rgb * k
    return np.concatenate([out, img[..., 3:]], -1) if img.shape[-1] > 3 else out


def relight_frame(plate: np.ndarray, source: np.ndarray, relit: np.ndarray, radius: float, strength: float = 1.0,
                  shift=(0.0, 0.0), plate_space: str = "linear", shot_space: str = "linear", light=None) -> np.ndarray:
    """One frame of Relight Transfer: `relit` moved by `shift` onto `source`, then its light moved onto `plate`, and with
    `light` the painted light kept where it is strong (`keep_light`).

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
    if light is not None:
        out = keep_light(out, plate, light).astype(np.float32)
    if plate_space == "sRGB":
        out[..., :3] = linear_to_srgb(out[..., :3])
    return out


FOLLOW_SPIKE = 2.0  # a matte more than this many times the median of the 7 frames around it is a spike, unless the tracker's mask grew as much
FOLLOW_WARN = 3.0  # the largest matte against the object's area: above it, the summary warns
FOLLOW_SIDE = 320  # the plate's own move, and what it puts in front of the object, are read at about this width
FOLLOW_STILL = 8  # frames: an object that keeps its place in the scene this long stands still in it, so the plate can cover it


def plate_move(before: np.ndarray, after: np.ndarray) -> tuple[float, float]:
    """How far the plate's background moved between two frames: (dy, dx) in pixels of these luma frames (H, W).

    The median, over tiles of a fifth of the width, of the shift that puts one frame on the
    other. An object in front that fills less than half of the tiles leaves the median alone (the horse of 11 Nov 2026
    fills a third of the frame). A flat plate, or a move of more than a quarter of a tile per frame, gives (0, 0)."""
    h, w = before.shape
    side = max(16, w // 5)
    moves = []
    for y in range(0, max(1, h - side + 1), side):
        for x in range(0, max(1, w - side + 1), side):
            a, b = before[y:y + side, x:x + side], after[y:y + side, x:x + side]
            if a.std() > 1e-3 and b.std() > 1e-3:
                dy, dx = phase_shift(a, b, side / 4)  # what moves `after` back onto `before`
                moves.append((-dy, -dx))
    if len(moves) < 3:
        return 0.0, 0.0
    dy, dx = np.median(np.asarray(moves), axis=0)
    return float(dy), float(dx)


def carry(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """A mask moved by whole pixels. What leaves the frame is lost, and what enters it is empty."""
    if not (dy or dx):
        return mask
    h, w = mask.shape
    out = np.zeros_like(mask)
    if abs(dy) < h and abs(dx) < w:
        out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = mask[max(-dy, 0):h - max(dy, 0), max(-dx, 0):w - max(dx, 0)]
    return out


RECORD_SIDE = 320  # PAINTAPLATE_RECORD keeps what Follow Matte was given at this width at most


def record(folder: str, masks, n: int, first, shot, base, zone: float, threshold: float, element) -> str:
    """With PAINTAPLATE_RECORD=<folder> in ComfyUI's environment, what Follow Matte was given, as one .npz file: the
    tracker's masks, the first-frame mask, the element, the shot and the plate, every k-th pixel so the width is
    RECORD_SIDE at most, in 8 bits. SAM and LTX need a GPU; this file does not: follow_matte(**replay(file)) runs the
    matte again anywhere, so a rule is tried on the real shot that showed its fault. Returns the file's path."""
    def small(a, after=0):  # `after`: the axes that follow the width (1 for an image's channels)
        if a is None or not np.size(a):
            return np.zeros((0,), np.uint8)
        a = np.asarray(a)
        k = max(1, -(-a.shape[a.ndim - 1 - after] // RECORD_SIDE))
        cut = a[..., ::k, ::k, :3] if after else a[..., ::k, ::k]
        return (np.clip(cut, 0, 1) * 255 + 0.5).astype(np.uint8)

    os.makedirs(folder, exist_ok=True)
    h, w = np.shape(shot)[1:3] if shot is not None else np.shape(masks)[-2:]
    path = os.path.join(folder, f"follow_matte_{w}x{h}_{n}f_{time.strftime('%Y%m%d_%H%M%S')}.npz")
    np.savez_compressed(path, masks=small(masks), first=small(first), element=small(element), shot=small(shot, 1), base=small(base, 1),
                        n=n, zone=zone, threshold=threshold)
    return path


def replay(path: str) -> dict:
    """follow_matte's arguments from a file that PAINTAPLATE_RECORD wrote: follow_matte(**replay(path))."""
    d = np.load(path)
    back = lambda k: d[k].astype(np.float32) / 255 if d[k].size else None  # noqa: E731
    return {"masks": back("masks") if d["masks"].size else np.zeros((0, 1, 1), np.float32), "n": int(d["n"]), "first": back("first"),
            "shot": back("shot"), "base": back("base"), "zone": float(d["zone"]), "threshold": float(d["threshold"]), "element": back("element")}


def follow_summary(n: int, seen=None, zones=0, placed=0, strays=0, held=0, added=0, most=0.0, alone=0, guarded=0,
                   smoothed=0, moved=0, fronts=0, gone=0, largest=None) -> str:
    """Follow Matte's summary for a person (Adrien, 13 Nov 2026): a headline, the warning next when there is one, then one
    line per rule that acted, and only those. The page writes « Paint matte (WxH): » or « Clean matte (WxH): » before it,
    and the GPU report reads that start. `seen` counts the frames where SAM 3.1 found the object, None when it returned
    no mask; `largest` is (the largest matte against the object's area on its frame, that frame); the other counts are
    follow_matte's, in frames."""
    def on(k):
        return f"{k} frame" + ("" if k == 1 else "s")
    lines = []
    if seen is None:
        lines.append("Held: first-frame mask, on every frame.")
    else:
        if zones:
            lines.append(f"Removed: paint zone outside the object's place, on {on(zones)} (SAM mask held the paint zone).")
        if placed:
            lines.append(f"Object stands still: its place of frame 0 added where the plate shows it, on {on(placed)}.")
        if strays:
            lines.append(f"Removed: SAM detections too far from the object, on {on(strays)}.")
        if held:
            lines.append(f"Held: last matte, on {on(held)} with no SAM mask.")
        if added:
            why = [f"up to {most:.1f}x SAM's mask"] * bool(most) + [f"{on(alone)} with no SAM mask"] * bool(alone)
            lines.append(f"Added: areas the shot changed next to the object, on {on(added)}" + (f" ({'; '.join(why)})." if why else "."))
    if guarded:
        lines.append(f"Removed: areas the shot changed away from the SAM mask, on {on(guarded)} (changes over 3x the object).")
    if smoothed:
        lines.append(f"Reduced: matte over {FOLLOW_SPIKE:g}x the frames around it, on {on(smoothed)}.")
    if moved:
        lines.append(f"Object moves from frame {moved}: occlusion by the plate not tested.")
    if fronts:
        lines.append(f"Removed: areas where the plate stands in front of the object, on {on(fronts)}.")
    if gone:
        lines.append(f"Removed: pieces that left the object's place, on {on(gone)}.")
    if largest is not None and largest[0] > FOLLOW_WARN:
        lines.insert(0, f"Warning: matte up to {largest[0]:.1f}x the object at frame {largest[1]}. Check the composite there.")
    return "\n  ".join([f"tracked on {seen or 0} of {n} frames."] + lines)


def matte_flicker(mattes, run: int = 3) -> np.ndarray:
    """How much a matte flickers, frame by frame (backlog D9; Adrien, 13 Nov 2026: a detection per frame lost an arm on 18
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


def follow_matte(masks: np.ndarray, n: int, first: np.ndarray, shot=None, base=None, zone: float = 1 / 16,
                 threshold: float = 0.1, workers: int = 8, element=None, tick=None):
    """One matte per frame from a tracker's masks, made safe for the composite. Returns (mattes (n, H, W), summary).

    A tracker can return no masks, fewer than the frames, lose part of an object, or find other objects by itself
    (SAM 3.1's video tracker found some on 102 of 121 frames from an empty first-frame mask, 28 Oct). A broken matte
    drops a good result from the composite, or leaves the erase pass with no frames to read. So the matte follows the
    object's own region, which starts as `element` (for paint, the pixels the edit changed on the first frame) or else
    as the first-frame mask, and moves by at most `zone` of the width per frame:
    - the tracker's mask within `zone` of the width of that region is the object; the rest is left out, even where a
      thin line joins it to the object (SAM's paint matte traced a smoke plume's edges, joined to a painted car). After
      frames where the object was not seen, the search grows by `zone` per frame, up to four times, so an object that
      comes back nearby is found again. The region keeps only the object's thick parts (an opening of 1/240 of the
      width), so it never creeps along a thin line; the matte itself keeps the thin parts near the object. An empty
      region searches nothing;
    - a paint's tracker is given its paint zone (`first`), which can be several times the object (`element`), and it
      returns that zone on its first frames before it finds the object (13 Nov 2026: 10 to 13 frames on each of five
      cow recordings, where the matte held the zone, 3.4 to 5.4 times the cow, then fell to a quarter in one frame).
      So with an element at most half the first-frame mask, a tracker's mask of two fifths of that mask or more is the
      zone. With `base`, on those frames the matte of an object that stands still (see below) is its place of frame 0,
      moved with the background, and the search keeps the zone; frames before the object is known to stand still are
      set when it is. An object found to move in the scene is followed as before. One that moves inside its paint
      zone is not found to move (its first matte is the zone, as at 32ea0a4), so the matte keeps to its place there;
    - an erased object (no `shot`, with `base`) is the plate's own: once it is known to stand still, its place of
      frame 0, moved with the background, is the object wherever the plate shows that place thick (an opening by 1/240
      of the width), seen by SAM or not (13 Nov 2026: the barn came out behind the horse, SAM found it again on frame
      101 and the matte came back on 103; now on 98, and it holds more of the barn after);
    - a frame where the object is not seen keeps the previous matte (with no mask at all, the first-frame mask holds);
    - with `shot` and `base` (the regenerated frames and the plate they were made over, (N, H, W, 3) in 0 to 1), the
      matte also takes the generated pixels connected to the object: the areas that touch the object or its region,
      within `zone` of it, where the shot differs from the plate by `threshold` more than the frame differs around the
      object (the median difference between one and three zones away: the frame's own level). LTX regenerates every
      pixel, so a frame that comes out brighter, softer or shifted differs from the plate everywhere: that raises its
      own level and adds nothing (at d95292c three frames brighter by 0.14 gave a matte of 5 times the object). A
      generated element stays in where the tracker dropped it, and the region moves with it;
    - with `shot` and `base`, the plate also says when something it holds stands in front of the object (11 Nov 2026:
      a cow painted behind a fence, a camera that pans, a horse that walks in front of the cow; SAM then returned
      nothing in one run and the horse in another, and LTX made the horse again where the cow went behind it). The
      plate's background moves from frame to frame by the median shift of its tiles (plate_move). A place is covered
      where the plate's colours, at two blurs (a quarter of `zone` for what is large, 1/160 of the width for where it
      ends), differ from the colours it first showed at the same place of the scene by `threshold` more than the places in view
      do, and at the object's own place also from that first look read inside the place, so what stood beside the
      object on frame 0 is no part of it (13 Nov 2026: a front object that touched the object on frame 0 kept it out
      for 6 frames after it came out; 3 now); or where they differ as much from the frame before, moved with the background (what moves in the plate: a
      dark leg over a dark rail reads as the rail), unless frame 0 said covered there on the frame before (what stood
      there has just left). At the object's own place, slits and holes under a quarter of a
      zone are closed. The plate holds no painted object, so none of this depends on what was generated. It applies
      from frame FOLLOW_STILL, to an object that kept its place in the scene until then (its matte stayed within half
      a zone of the first one, moved with the background). Its region then holds its place of frame 0 and its covered
      part, and moves with the background, as a held matte does. A changed area counts when it lies mostly in view
      and touches, in view, the tracker's mask or, with a thick part, the region (a thin line of changes runs along
      the outline of what stands in front); at the places where the object stood on frame 0, which frame 0 showed in
      view, what is covered never counts. A tracker's mask that lies mostly on covered places is what stands in
      front, and is left out; so is each piece of it that does, as for an erase (13 Nov 2026: pieces of SAM's mask on
      the horse's head, over the cow's place). What is found counts only at the object's place of
      frame 0, with a margin of half a zone, and where it is joined to it there while a quarter of the place holds
      the object: a piece that leaves the place, with what stands in front or alone, is not the object (12 Nov
      2026: LTX drew the cow walking away with the horse, then gave the horse its head); when less than a quarter
      does, a found area that reaches beyond the margin is left out whole, not cut at it (13 Nov 2026: such a strip
      stayed on the horse's chest). Of a changed area, what is
      covered counts only in that margin, and only when a quarter of the area at most is covered. So the matte is empty while the object is hidden, takes it again where it
      comes out, and leaves out what stands in front. An object that moves in the scene over its first frames is
      followed as before;
    - with `base` and no `shot`, the matte is an erase's: the frames the tracker read are the plate, and the object is
      the plate's own (12 Nov 2026: an erased barn passed behind the horse; the matte held its last 30 px at one place
      of the frame for 65 frames, and left the barn out as too far when the tracker found it again). The plate is
      asked as above for an object that stands still: the region and a held matte move with the background, a held
      matte drops what the plate covers, and a tracker's mask that lies mostly on covered places is left out. So is each
      piece of it that does: it lies on what stands in front (12 Nov 2026: 43 to 55 px on the horse's head, beside the
      barn that the horse was hiding; the composite grew them to 1.2% of the frame). Otherwise the
      tracker's mask is taken wherever it goes: when it is the matte of the frame before, whole, on places that
      changed, the object moves by itself, and the plate is not asked again;
    - changes larger than 3 times the object's largest area keep only what lies at the tracker's own mask, and the
      region does not follow them. A matte more than FOLLOW_SPIKE times the median of the 7 frames around it, when the
      tracker's own mask did not grow as much, keeps only what those frames hold too. So the matte's area changes
      smoothly, and a difference over the whole frame cannot move the search.
    `tick`, called once per frame, lets the caller stop the loop by raising (ComfyUI's interrupt check, in nodes.py).
    The summary is follow_summary's: a headline, a warning when the largest matte is more than FOLLOW_WARN times the
    object's area (the tracker's mask on that frame with the part of its place that the plate covers, or where it was
    last seen), then one line per rule that acted.
    """
    if os.environ.get("PAINTAPLATE_RECORD"):
        record(os.environ["PAINTAPLATE_RECORD"], masks, n, first, shot, base, zone, threshold, element)
    masks = np.asarray(masks, np.float32).reshape((-1,) + np.shape(masks)[-2:]) if np.size(masks) else np.zeros((0, 1, 1), np.float32)
    first = np.asarray(first, np.float32)
    first = first[0] if first.ndim == 3 else first
    h, w = (shot.shape[1:3] if shot is not None else masks.shape[1:3] if len(masks) else first.shape[-2:])
    fit = lambda m: (m if m.shape == (h, w) else resize_to(m.astype(np.float32), h, w)) > 0.5  # noqa: E731
    seed = fit(first)
    el = None if element is None or not np.size(element) else fit(np.asarray(element, np.float32).reshape(np.shape(element)[-2:]))
    tracked = lambda t: fit(masks[t]) if t < len(masks) else np.zeros((h, w), bool)  # noqa: E731
    grow = lambda m, r: dilate(m.astype(np.uint8), min(r, max(h, w))) > 0  # noqa: E731
    eight = np.ones((3, 3), bool)

    compare = shot is not None and base is not None
    real = shot is None and base is not None  # an erase: the frames the tracker read are the plate, and the object is the plate's own

    def differ(t):  # how far the shot is from the plate under it, per pixel, without one-pixel edges from a small shift
        b = base[min(t, len(base) - 1)]
        b = b if b.shape[:2] == (h, w) else resize_to(b, h, w)
        return ndimage.gaussian_filter(np.abs(shot[min(t, len(shot) - 1)][..., :3] - b[..., :3]).max(axis=-1), 1.0)
    reach, thin = max(2.0, zone * w), max(1.0, w / 240)

    def bulk(m):  # a mask without its thin lines (an opening by `thin`), worked out in the mask's own box
        if not m.any():
            return m
        ys, xs, r = np.flatnonzero(m.any(1)), np.flatnonzero(m.any(0)), int(np.ceil(thin)) + 1
        box = (slice(max(ys[0] - r, 0), ys[-1] + r + 1), slice(max(xs[0] - r, 0), xs[-1] + r + 1))
        out = np.zeros_like(m)
        out[box] = grow(~grow(~m[box], thin), thin)
        return out

    def touching(m, to):  # the connected parts of a mask that touch another one, worked out in the mask's own box
        ys, xs = np.flatnonzero(m.any(1)), np.flatnonzero(m.any(0))
        box = (slice(ys[0], ys[-1] + 1), slice(xs[0], xs[-1] + 1))
        parts, _ = ndimage.label(m[box], structure=eight)
        keep = np.unique(parts[m[box] & to[box]])
        out = np.zeros_like(m)
        out[box] = np.isin(parts, keep[keep > 0])
        return out

    def in_view(m, hide):  # a mask without its pieces that lie mostly on covered places
        parts, count = ndimage.label(m, structure=eight)
        areas, covered = np.bincount(parts.ravel(), minlength=count + 1), np.bincount(parts[hide], minlength=count + 1)
        return m & (2 * covered <= areas)[parts]
    k = max(1, -(-w // FOLLOW_SIDE))  # the plate is read small, at the pixels that `record` keeps
    soft = (max(1.0, zone * (w // k) / 4), max(1.0, (w // k) / 160))  # two blurs: a quarter of a zone says that something large stands there, 1/160 of the width says where it ends

    def plate(t):  # the plate, small: its luma, to measure its move, and its colours at the two blurs, to compare places and not their texture
        b = base[min(t, len(base) - 1)]
        b = (b if b.shape[:2] == (h, w) else resize_to(b, h, w))[::k, ::k, :3]  # every k-th pixel, as `record` keeps them: a replay reads the same plate
        return luma(b), [ndimage.gaussian_filter(b, (r, r, 0), truncate=2.5) for r in soft]

    def read_in(b, m):  # the plate's colours at the two blurs, read inside a mask only: what stands beside it does not mix in
        mf = m.astype(np.float32)
        return [ndimage.gaussian_filter(b * mf[..., None], (r, r, 0), truncate=2.5)
                / np.maximum(ndimage.gaussian_filter(mf, r, truncate=2.5), 1e-6)[..., None] for r in soft]

    def front(colours, at, was, levels, stood, past, by, far):  # where the plate covers what it first showed at this place of the scene (small), the levels of the places in view, and what that first look alone says
        hs, ws = colours[0].shape[:2]
        oy, ox = int(at[0]), int(at[1])
        if abs(oy) > hs or abs(ox) > ws:  # the scene's map holds one frame on each side of frame 0: further away, no place is known to be covered
            return np.zeros((hs, ws), bool), levels, np.zeros((hs, ws), bool)
        there = (slice(hs - oy, 2 * hs - oy), slice(ws - ox, 2 * ws - ox))  # this frame, in the scene's map
        known, levels = learnt[there] > 0, list(levels)
        calm = (learnt[there] == 1) & ~was  # the level comes from the places of frame 0 while 64 of them are in view, then from every known place
        calm = calm if int(calm.sum()) >= 64 else known & ~was
        covered = known.copy()
        for i in (0, 1):
            apart = np.abs(colours[i] - ground[i][there]).max(axis=-1)
            levels[i] = float(np.median(apart[calm])) if int(calm.sum()) >= 64 else levels[i]
            covered &= (apart > threshold + levels[i]) & (np.abs(colours[i] - ground_in[i][there]).max(axis=-1) > threshold + levels[i])
        new = ~known  # the map learns a place the first time the plate shows it, away from the frame's edge where a blur reads the frame's own border
        new[:rim], new[hs - rim:], new[:, :rim], new[:, ws - rim:] = False, False, False, False
        for i in (0, 1):
            ground[i][there][new], ground_in[i][there][new] = colours[i][new], colours[i][new]
        learnt[there][new] = 2
        against = covered.copy()  # covered, by that first look alone
        oy, ox = int(by[0]), int(by[1])  # what moves in the plate stands in front too: a dark leg over a dark rail reads as the rail, and differs from the frame before
        here = (slice(max(oy, 0), hs + min(oy, 0)), slice(max(ox, 0), ws + min(ox, 0)))
        there = (slice(max(-oy, 0), hs - max(oy, 0)), slice(max(-ox, 0), ws - max(ox, 0)))
        apart = np.abs(colours[1][here] - past[there]).max(axis=-1)
        covered[here] |= (apart > threshold + float(np.median(apart))) & ~far[there]  # but not where frame 0 said covered on the frame before: what stood there has just left
        gap = max(1.0, zone * ws / 4)  # at the object's own place, what stands in front has no slit or hole under a quarter of a zone: a dark coat over a dark rail reads as the rail
        inside = dilate((covered & stood).astype(np.uint8), gap) > 0
        return covered | (stood & ~(dilate((~inside).astype(np.uint8), gap) > 0)), levels, against

    line = el if el is not None and el.any() else seed  # the object's own region
    given = int(seed.sum())  # the first-frame mask the tracker was given
    zoned = line is el and 2 * int(el.sum()) <= given  # a paint zone at least twice the object: the tracker returns the zone first
    out, cores, prev, peak = np.zeros((n, h, w), np.float32), np.zeros((n, h, w), bool), seed, int(seed.sum())
    size, last = np.ones(n, np.int64), max(int(line.sum()), 1)  # the object's area on each frame
    seen = strays = held = added = alone = lost = guarded = smoothed = fronts = zones = placed = 0
    most, chunk = 1.0, 2 * max(1, workers)
    still = None  # does the object keep its place in the scene? Not known before frame FOLLOW_STILL
    waiting = []  # the zone's frames before it is known whether the object stands still, each with the object's place
    ground = ground_in = learnt = before = past = home = None  # the scene's map (the softened colours each place first showed, and which places it holds), the frame before's luma and colours, the first matte moved with the background
    rim = int(np.ceil(2.5 * soft[0]))  # as far as the large blur reads
    gone = moved = 0  # frames where a piece that left the object's place was left out; the frame where the object was seen to move in the scene
    inside = np.ones((h, w), bool)  # the places that frame 0 showed, moved with the background: an object cut by the frame's edge shows more of itself as the plate moves, and that is not a move
    seat = np.zeros(2)  # the background's move at the frame before, in whole small pixels
    open0 = line  # where the object stood on frame 0, moved with the background: frame 0 showed these places in view, so the plate knows what covers them
    place, rest = np.zeros(2), np.zeros(2)  # the background's move since frame 0 (small pixels), and what is left of it under a whole pixel
    was, floor = np.zeros((-(-h // k), -(-w // k)), bool), (0.0, 0.0)  # the covered places of the frame before (small), and the levels of the places in view
    far = was  # the places that frame 0 alone said covered, on the frame before
    with ThreadPoolExecutor(max(1, workers)) as pool:  # numpy and scipy release the GIL; a chunk at a time, so the differences of a long shot never sit in memory together
        for start in range(0, n, chunk):
            block = list(pool.map(differ, range(start, min(n, start + chunk)))) if compare else None
            plates = list(pool.map(plate, range(start, min(n, start + chunk)))) if base is not None and still is not False else None
            for t in range(start, min(n, start + chunk)):
                if tick:
                    tick()
                s = tracked(t)
                hide, blocked = None, False  # where the plate stands in front of the object's place; whether the tracker's mask was left out for it
                if plates is not None and still is not False:
                    lum, colours = plates[t - start]
                    if t == 0:  # frame 0 in the middle of the scene's map, with room for one frame on each side
                        hs, ws = lum.shape
                        ground, learnt = [np.zeros((3 * hs, 3 * ws, 3), np.float32) for _ in colours], np.zeros((3 * hs, 3 * ws), np.uint8)
                        for i in (0, 1):
                            ground[i][hs:2 * hs, ws:2 * ws] = colours[i]
                        learnt[hs:2 * hs, ws:2 * ws] = 1
                        stood, b0 = open0[::k, ::k], (base[0] if base[0].shape[:2] == (h, w) else resize_to(base[0], h, w))[::k, ::k, :3]
                        ground_in = [g.copy() for g in ground]  # the object's place also read inside itself: what stood beside it on frame 0 is not its first look
                        for i, inner in enumerate(read_in(b0, stood)):
                            ground_in[i][hs:2 * hs, ws:2 * ws][stood] = inner[stood]
                    else:
                        dy, dx = plate_move(before, lum)
                        place += (dy, dx)
                        rest += (dy * k, dx * k)
                        step = np.rint(rest).astype(int)
                        rest -= step
                        open0, inside = carry(open0, int(step[0]), int(step[1])), carry(inside, int(step[0]), int(step[1]))
                        if still is None:
                            home = carry(home, int(step[0]), int(step[1]))
                        else:  # the region and a held matte move with the background
                            line, prev = carry(line, int(step[0]), int(step[1])) | open0, carry(prev, int(step[0]), int(step[1]))  # it stands still: its region holds its place of frame 0
                            was, floor, far = front(colours, np.rint(place), was, floor, open0[::k, ::k], past, np.rint(place) - seat, far)
                            hide = np.repeat(np.repeat(was, k, 0), k, 1)[:h, :w]
                    before, past, seat = lum, colours[1], np.rint(place)
                near = grow(line, reach * min(1 + lost, 4)) if line.any() else np.zeros((h, w), bool)
                core = s & near  # SAM's mask near the region: what lies further away is left out, even joined to it
                strays += bool((s & ~near).any())
                here = grow(open0, reach / 2) if hide is not None else None  # the object's place of frame 0, with a margin of half a zone
                if hide is not None and 2 * int((core & hide).sum()) > int(core.sum()):  # most of the tracker's mask lies on covered places
                    if real and 4 * int((core & prev).sum()) >= 3 * max(int(core.sum()), int(prev.sum())) and 4 * int(core.sum()) >= int(line.sum()):
                        still, hide, moved = False, None, t  # an erased object is the plate's own: the matte of the frame before, whole, on places that changed, is the object moving by itself
                    else:
                        core, blocked = np.zeros((h, w), bool), True  # it is what stands in front
                elif hide is not None and not real:
                    core = in_view(core, hide) & ~(hide & ~here)  # a piece on what stands in front is left out; beyond the place, only what is in view counts
                elif hide is not None:
                    core = in_view(core, hide)  # of an erased object's mask, a piece that lies mostly on covered places is on what stands in front
                peak = max(peak, int(core.sum()))
                found, follows = core, True
                if real and hide is not None:  # an erased object stands still: its place of frame 0, where the plate shows it thick, is the object, seen by SAM or not
                    shows = bulk(open0 & ~hide) & ~found
                    if shows.any():
                        found, placed = found | shows, placed + 1
                if block is not None and (core.any() or line.any()):
                    d, anchor = block[t - start], core | line
                    within = grow(anchor, reach)
                    around = grow(anchor, 3 * reach) & ~within  # between one and three zones from the object
                    level = float(np.median(d[around])) if int(around.sum()) >= 64 else 0.0  # what this frame differs by, object or not
                    changed = ndimage.binary_opening(d > threshold + level, structure=eight) & within
                    labels, _ = ndimage.label(changed, structure=eight)
                    if hide is None:
                        joined = np.unique(labels[changed & grow(anchor, thin)])
                        gain = np.isin(labels, joined[joined > 0])  # the changed areas that touch the object or its region
                    else:  # the changed areas in view that touch the object, or with a thick part its region in view, and that lie mostly in view; never what covers the object's own place
                        shown = changed & ~hide
                        joined = np.unique(labels[(shown & grow(core, thin)) | (bulk(shown) & grow(line & ~hide, thin))])
                        joined = joined[joined > 0]
                        areas, covered = np.bincount(labels[changed]), np.bincount(labels[changed & hide], minlength=int(labels.max()) + 1)
                        gain = np.isin(labels, joined[2 * covered[joined] <= areas[joined]]) & ~hide  # of an area that lies mostly in view, what is in view
                        gain |= np.isin(labels, joined[4 * covered[joined] <= areas[joined]]) & hide & here & ~open0  # and, when a quarter of it at most is covered, its covered part in the margin around the place: there the plate may have first shown something that has left
                    if int(gain.sum()) > 3 * max(peak, 1):  # never a runaway: changes far beyond the object's size stay out
                        gain, follows = (gain & grow(core, reach) if core.any() else np.zeros_like(core)), False
                        guarded += 1
                    if int((gain & ~core).sum()) > 0.25 * int(core.sum()) + 16:
                        added += 1
                        if core.any():
                            most = max(most, float((core | gain).sum()) / int(core.sum()))
                        else:
                            alone += 1  # SAM returned nothing here: no ratio to SAM's mask
                    found = core | gain
                left = False  # whether all that was found has left the object's place
                if hide is not None and not real and found.any():  # a painted object that stands still: a piece that has left its place, with what stands in front or alone, is not the object
                    whole = found
                    if 4 * int((found & here).sum()) >= int(open0.sum()):  # the object is seen at its place: what is joined to it there counts
                        found = touching(found, here)
                    else:  # it is not: a found area that reaches beyond the place's margin is leaving it, and is left out whole
                        parts, _ = ndimage.label(found, structure=eight)
                        leaving = np.unique(parts[found & ~here])
                        found = found & ~np.isin(parts, leaving[leaving > 0])
                    core = core & found
                    gone += bool(bulk(whole & ~found).any())
                    left = not found.any()
                seen += bool(core.any())
                hidden = int((line & hide).sum()) if hide is not None else 0  # the part of the object's place that the plate covers
                last = int(core.sum()) + hidden if core.any() else last
                size[t], cores[t] = last, core
                fronts += blocked or (hide is not None and 2 * hidden >= max(int(line.sum()), 1))
                if found.any():
                    f, region = ndimage.binary_fill_holes(found), (found if follows else core)
                    thick = bulk(region)  # the object without its thin lines: the region never creeps along them
                    kept = line & hide if hide is not None else None
                    line, lost = (ndimage.binary_fill_holes(thick) if thick.any() else ndimage.binary_fill_holes(region)), 0
                    if kept is not None:
                        line |= kept  # the region keeps its covered part
                elif left:  # all that was found has left the object's place: nothing of it is there, and no last matte holds
                    f = np.zeros((h, w), bool)
                elif hide is not None:  # not seen: the last matte holds where its place is in view, and the search grows only around a place in view
                    f, lost = (bulk(prev & ~hide) if hidden else prev), lost + (2 * hidden < int(line.sum()))  # no crumbs of a matte that the plate covers
                    held += bool(f.any())
                else:  # the object is not seen: the last matte holds, and the search grows
                    f, lost = prev, lost + 1
                    held += bool(prev.any())
                if zoned and plates is not None and still is not False and 5 * int(s.sum()) >= 2 * given:  # the tracker's mask is the zone
                    own = ndimage.binary_fill_holes(open0)  # the matte shows the object's place of frame 0; the search keeps the zone
                    if still:
                        f, zones = f & own, zones + 1
                    else:
                        waiting.append((t, own))
                out[t], prev = f, f
                if plates is not None and t == 0:
                    home = f
                elif plates is not None and still is None:
                    body = bulk(found)  # without thin lines: a changed area that a thin line joins to the object is not the object moving
                    if body.any() and bulk(touching(body, grow(home, thin)) & ~grow(home, reach / 2) & inside).any():
                        still, moved = False, t  # it moves in the scene: followed as before
                    elif t >= min(FOLLOW_STILL, n - 1):
                        still = True
                if still and waiting:  # it stands still: the zone's frames before this one show its place too
                    for j, own in waiting:
                        out[j] *= own
                    zones, prev, waiting = zones + len(waiting), out[t] > 0.5, []
    areas, solid = out.reshape(n, -1).sum(1), cores.reshape(n, -1).sum(1)
    for t in range(n):  # no frame several times its neighbours, unless the tracker's own mask is
        lo, hi = max(0, t - 3), min(n, t + 4)
        usual = FOLLOW_SPIKE * float(np.median(areas[lo:hi])) + 16
        if areas[t] > usual and solid[t] <= FOLLOW_SPIKE * float(np.median(solid[lo:hi])) + 16:
            calm = np.zeros((h, w), bool)
            for j in range(lo, hi):
                if j != t and areas[j] <= usual:
                    calm |= out[j] > 0.5
            out[t] = cores[t] | ((out[t] > 0.5) & grow(calm, thin))
            smoothed += 1
    largest = None
    if n:
        ratio = out.reshape(n, -1).sum(1) / size
        worst = int(ratio.argmax())
        largest = (float(ratio[worst]), worst)
    tracked_any = bool(len(masks)) and bool(masks.any())
    counts = dict(seen=seen, zones=zones, placed=placed, strays=strays, held=held, added=added, most=most, alone=alone) if tracked_any else {}
    return out, follow_summary(n, guarded=guarded, smoothed=smoothed, moved=moved, fronts=fronts, gone=gone, largest=largest, **counts)


GRAIN_UNIT = _grain_unit()


# ---------- SDR to HDR: the HDR shot's level fitted to the plate ----------
HDR_FLOOR = 2.0 ** -14  # the smallest normal half float: darker values carry no usable ratio
HDR_MIDTONES = (2.0 ** -6, 2.0 ** -0.5)  # plate luminance where the level is measured: above the noise, below SDR's white


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


def hdr_match(n: int, shot_at, plate_at, changed_at, *, grow: float = 24.0, step: int = 8, samples: int = 1_500_000,
              workers: int = 8):
    """The HDR shot at the level of the plate it is composited onto: (frames, report).

    SDR to HDR picks its own exposure and white balance, while the plate's untouched pixels hold the scene's real values.
    One gain per channel (hdr_level) is measured where the edits changed nothing (outside `changed_at(i)`, a mask at any
    size, grown by `grow` plate pixels), on a grid every `step` plate pixels, over the whole shot, so the level cannot
    flicker; the mid-tones decide it, then every pixel is scaled by it. A gain keeps every ratio, so new content keeps the
    range SDR to HDR gave it above the plate's white. Frames may differ in size: samples are taken at the same places of
    each frame. Too few untouched mid-tones (an edit over the whole frame) leave the shot as it was made."""
    first = plate_at(0)
    hp, wp = first.shape[:2]
    ys = np.minimum(np.arange(step // 2, hp, step), hp - 1)
    xs = np.minimum(np.arange(step // 2, wp, step), wp - 1)
    stride = max(1, int(np.ceil(n * len(ys) * len(xs) / samples)))

    def sample(i):
        s, p, m = shot_at(i), plate_at(i), changed_at(i)
        hs, ws = s.shape[:2]
        hm, wm = m.shape[:2]
        near = dilate((m > 0.02).astype(np.float32), grow * hm / hp)
        keep = near[(ys * hm // hp)[:, None], (xs * wm // wp)[None, :]] < 0.5
        return s[(ys * hs // hp)[:, None], (xs * ws // wp)[None, :], :3][keep], p[ys[:, None], xs[None, :], :3][keep]

    with ThreadPoolExecutor(max(1, workers)) as pool:  # numpy releases the GIL
        parts = list(pool.map(sample, range(0, n, stride)))
    shot = np.concatenate([a for a, _ in parts]) if parts else np.zeros((0, 3), np.float32)
    plate = np.concatenate([b for _, b in parts]) if parts else np.zeros((0, 3), np.float32)
    stops = hdr_level(shot, plate)
    if stops is None:
        return [np.array(shot_at(i)[..., :3], np.float32) for i in range(n)], {
            "samples": len(shot), "fitted": False,
            "text": f"{len(shot)} untouched samples, too few mid-tones to measure: the HDR shot as it was made"}
    fitted, lum = apply_level(shot, stops), plate @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    mid = np.all((fitted > HDR_FLOOR) & (plate > HDR_FLOOR), axis=-1) & (lum >= HDR_MIDTONES[0]) & (lum <= HDR_MIDTONES[1])
    error = float(np.median(np.abs(np.log2(fitted[mid] / plate[mid])))) if mid.any() else float("nan")
    with ThreadPoolExecutor(max(1, workers)) as pool:
        frames = list(pool.map(lambda i: apply_level(shot_at(i), stops), range(n)))
    return frames, {"samples": len(shot), "fitted": True, "stops": [float(x) for x in stops], "error": error,
                    "text": f"{len(shot)} untouched samples; the level moves by {', '.join(f'{x:+.2f}' for x in stops)} stops "
                            f"(R, G, B), nothing compressed; median mid-tone error after it {error:.3f} stops"}

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
