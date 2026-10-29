"""The numpy maths behind the nodes: fitting generated frames to the plate, filling, relighting.

Frames are (H, W, C) float arrays and masks (H, W); stacks add a first axis. Nothing here imports
torch or ComfyUI, so every function is tested in plain Python (tests/test_mathops.py).
"""
from __future__ import annotations

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

    `plate_at(i)` and `gen_at(i)` give frame i as (h, w, C) float arrays of the same size; `masks` is
    (N or 1, any height, any width). The mask edge, the shift and the colour match are smoothed over
    `steady` frames on each side, so nothing in the composite changes from one frame to the next unless
    the shot does. Masks and colour fields are computed at about 480 px, alignment at about 512 px.
    """
    tick = progress or (lambda: None)
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

    def measure(i):  # pass 1: the shift and the colour field of one frame, at low resolution
        p, g = plate_at(i), gen_at(i)
        dy = dx = 0.0
        if align:
            keep = 1.0 - resize_to(small[i], ha, wa)
            dy, dx = phase_shift(structure(shrink(p, al)) * keep, structure(shrink(g, al)) * keep, max_shift / al)
            dy, dx = dy * al, dx * al
        field = None
        if match_color and small[i].max() > 0.02:
            gl = shrink(g, lo)
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
        own = np.median([noise_sigma(gen_at(i)) for i in picks], 0)
        level = np.sqrt(np.maximum(target ** 2 - own ** 2, 0.0)) * grain

    def apply(i):  # pass 2: full size, only around the edit
        g = gen_at(i)
        dy, dx = shifts[i]
        if abs(dy) > 0.05 or abs(dx) > 0.05:
            g = ndimage.shift(g, (dy, dx, 0), order=1, mode="nearest")
        m = resize_to(small[i], h, w)
        ys, xs = np.nonzero(m > 1.0 / 1024)
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


# Light may change by 4 stops down and 3 up: night needs about that. At 0.25 (2 stops) a night relight stayed in dusk.
RATIO_RANGE = (1.0 / 16.0, 8.0)


def relight(plate: np.ndarray, source: np.ndarray, relit: np.ndarray,
            radius: int, strength: float = 1.0) -> np.ndarray:
    """Move the light of `relit` onto `plate`, keeping the plate's own detail.

    All three images are linear light. `source` and `relit` share the working
    size; `plate` can be larger. The change of light is the ratio relit/source,
    smoothed with an edge-aware filter; the plate is multiplied by it, so its
    texture, grain and values above 1.0 stay its own.
    """
    guide = np.log(luma(source).clip(0) + 1e-3)
    eps = 1e-2 * max(guide.var(), 1e-6)  # smooth enough that fine detail never enters the ratio
    ratio = (guided_filter(guide, relit[..., :3].clip(0), radius, eps) + 1e-3) / \
            (guided_filter(guide, source[..., :3].clip(0), radius, eps) + 1e-3)
    ratio = ndimage.median_filter(ratio, size=(3, 3, 1))  # isolated specks at sharp edges go
    ratio = ndimage.gaussian_filter(np.clip(ratio, *RATIO_RANGE), (1.0, 1.0, 0)) ** strength
    if ratio.shape[:2] != plate.shape[:2]:
        ratio = resize_to(ratio, plate.shape[0], plate.shape[1])
    out = plate.copy()
    out[..., :3] = plate[..., :3] * ratio
    return out


def relight_frame(plate: np.ndarray, source: np.ndarray, relit: np.ndarray, radius: int, strength: float = 1.0,
                  align: bool = True) -> np.ndarray:
    """One frame of Relight Transfer: `relit` aligned to `source`, then its light moved onto `plate`.

    The ratio of light is computed at the size of `source` and `relit`, then enlarged to the plate. Light
    is smooth, so the workflows give them at half the plate's size: converting them to linear light then
    costs a quarter. `radius` is in pixels of that size; a shift counts as misalignment up to 8 plate pixels.
    """
    if align:
        dy, dx = phase_shift(structure(source), structure(relit), 8.0 * source.shape[1] / plate.shape[1])
        if dy or dx:
            relit = ndimage.shift(relit, (dy, dx, 0), order=1, mode="nearest")
    return relight(plate, source, relit, max(1, radius), strength).astype(np.float32)


def follow_matte(masks: np.ndarray, n: int, first: np.ndarray, shot=None, base=None, zone: float = 1 / 16,
                 threshold: float = 0.1, workers: int = 8, element=None):
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
      width), so it never creeps along a thin line; the matte itself keeps the thin parts near the object;
    - a frame where the object is not seen keeps the previous matte (with no mask at all, the first-frame mask holds);
    - with `shot` and `base` (the regenerated frames and the plate they were made over, (N, H, W, 3) in 0 to 1), the
      matte also takes every pixel the shot changed by `threshold` or more within `zone` of the object's region: a
      generated element stays in where the tracker dropped it, and the region moves with it. Where the shot equals the
      plate, losing the matte changes nothing visible.
    """
    masks = np.asarray(masks, np.float32).reshape((-1,) + np.shape(masks)[-2:]) if np.size(masks) else np.zeros((0, 1, 1), np.float32)
    first = np.asarray(first, np.float32)
    first = first[0] if first.ndim == 3 else first
    h, w = (shot.shape[1:3] if shot is not None else masks.shape[1:3] if len(masks) else first.shape[-2:])
    fit = lambda m: (m if m.shape == (h, w) else resize_to(m.astype(np.float32), h, w)) > 0.5  # noqa: E731
    seed = fit(first)
    el = None if element is None or not np.size(element) else fit(np.asarray(element, np.float32).reshape(np.shape(element)[-2:]))
    tracked = lambda t: fit(masks[t]) if t < len(masks) else np.zeros((h, w), bool)  # noqa: E731
    grow = lambda m, r: dilate(m.astype(np.uint8), min(r, max(h, w))) > 0  # noqa: E731

    changes = None
    if shot is not None and base is not None:
        def change(t):  # where the shot differs from the plate under it, without one-pixel edges from a small shift
            b = base[min(t, len(base) - 1)]
            b = b if b.shape[:2] == (h, w) else resize_to(b, h, w)
            d = ndimage.gaussian_filter(np.abs(shot[min(t, len(shot) - 1)][..., :3] - b[..., :3]).max(axis=-1), 1.0)
            return ndimage.binary_opening(d > threshold, structure=np.ones((3, 3), bool))
        with ThreadPoolExecutor(max(1, workers)) as pool:  # numpy and scipy release the GIL
            changes = list(pool.map(change, range(n)))
    reach, thin = max(2.0, zone * w), max(1.0, w / 240)
    line = el if el is not None and el.any() else seed  # the object's own region
    out, prev, peak = np.zeros((n, h, w), np.float32), seed, int(seed.sum())
    seen = strays = held = added = lost = 0
    most = 1.0
    for t in range(n):
        s = tracked(t)
        near = grow(line, reach * min(1 + lost, 4)) if line.any() else np.ones((h, w), bool)
        core = s & near  # SAM's mask near the region: what lies further away is left out, even joined to it
        strays += bool((s & ~near).any())
        peak = max(peak, int(core.sum()))
        found = core
        if changes is not None:
            gain = changes[t] & grow(core | line, reach)
            if int(gain.sum()) > 3 * max(peak, 1):  # never a runaway: changes far beyond the object's size stay out
                gain = changes[t] & grow(core, reach) if core.any() else np.zeros_like(s)
            if int((gain & ~core).sum()) > 0.25 * int(core.sum()) + 16:
                added += 1
                most = max(most, float((core | gain).sum()) / max(int(core.sum()), 1))
            found = core | gain
        seen += bool(core.any())
        if found.any():
            f = ndimage.binary_fill_holes(found)
            thick = grow(~grow(~found, thin), thin)  # the object without its thin lines: the region never creeps along them
            line, lost = (ndimage.binary_fill_holes(thick) if thick.any() else f), 0
        else:  # the object is not seen: the last matte holds, and the search grows
            f, lost = prev, lost + 1
            held += bool(prev.any())
        out[t], prev = f, f
    if not len(masks) or not masks.any():
        summary = "SAM 3.1 returned no mask: the first-frame mask holds on every frame"
    else:
        summary = f"SAM 3.1 found the object on {seen} of {n} frames"
        if strays:
            summary += f"; what it found further than the object can move, on {strays} frame(s), is left out"
        if held:
            summary += f"; the last matte held on {held} frame(s) where the object was not seen"
        if added:
            summary += f"; the shot's changes near the object added area on {added} frame(s), up to {most:.1f} times SAM's mask"
    return out, summary

GRAIN_UNIT = _grain_unit()
