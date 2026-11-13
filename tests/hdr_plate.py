"""An HDR test plate made from an SDR movie, and the level of an edit against it at the seam: the laptop's proof that the
way back from the model space keeps the plate's levels (PLA, the colour review's proposal A), without a pod.

  make  The movie becomes half-float EXR frames in scene-linear Rec.709, lifted by the inverse of core's tone mapping to
        a peak near `--peak`. The models then see the movie as it was, so the same seed and strokes make the edit of the
        SDR case, and two runs differ only by the way back to the plate.
  seam  In the export's zip: the result against the plate on the ring of new pixels at the matte's edge, by the plate's
        luminance. The median level in stops: 0 is the plate's level. It also checks that the untouched pixels are the
        plate's. Written to seam.md beside the zip.

With ComfyUI's Python (numpy, scipy, av, OpenEXR), no GPU, on any version of the pack:
  python tests/hdr_plate.py make --source /data/ComfyUI/input/plates/horse.mp4 --out /data/ComfyUI/input/plates/horse_hdr
  python tests/hdr_plate.py seam --plate /data/ComfyUI/input/plates/horse_hdr --export ~/paintaplate_gpu/hdr_dev/export.zip
"""
import argparse
import glob
import os
import sys
import tempfile
import time
import zipfile

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plateio  # noqa: E402

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
BANDS = ((0.02, 0.18), (0.18, 0.5), (0.5, 1.0), (1.0, np.inf))
NEW = 0.98  # the matte from which a pixel is the edit's alone


def lift(srgb: np.ndarray, peak: float) -> np.ndarray:
    """sRGB values (0 to 1) to scene-linear Rec.709 up to `peak`: core's sRGB decode, then the inverse of core's tone
    mapping at that peak. It is ocio.out_of_model's equation, written again so that this runs on any version of the pack."""
    x = srgb.astype(np.float32)
    rgb = np.where(x <= 0.04045, x / 12.92, np.power((np.maximum(x, 0.04045) + 0.055) / 1.055, 2.4)).astype(np.float32)
    lum = np.maximum(rgb @ LUMA, 0.0)[..., None]
    was = 2.0 * lum / ((1.0 - lum) + np.sqrt((1.0 - lum) ** 2 + 4.0 * lum / (peak * peak)))
    return (rgb * (was / np.maximum(lum, np.finfo(np.float32).tiny))).astype(np.float32)


def make(source: str, out: str, peak: float = 7.0, frames: int = 121) -> dict:
    import av
    start = time.time()
    with av.open(source) as c:
        fps = float(c.streams.video[0].average_rate or 0)
        rgb = [f.to_ndarray(format="rgb24") for _, f in zip(range(frames), c.decode(video=0))]
    name = os.path.basename(os.path.normpath(out))
    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, f"{name}.*.exr")):  # a longer plate of an earlier run would stay the largest
        os.remove(old)
    paths, peaks = [os.path.join(out, f"{name}.{1001 + i:04d}.exr") for i in range(len(rgb))], [0.0] * len(rgb)

    def at(i):
        f = lift(rgb[i] / 255.0, peak)
        peaks[i] = float((f @ LUMA).max())
        return f
    plateio.write_exrs(at, paths, fps=fps)
    h, w = rgb[0].shape[:2]
    info = {"frames": len(paths), "width": w, "height": h, "fps": fps, "peak": max(peaks), "seconds": time.time() - start}
    print(f"{out}: {len(paths)} frames, {w} x {h}, {fps:g} fps, half-float EXR in scene-linear Rec.709, peak "
          f"{info['peak']:.2f}, in {info['seconds']:.0f} s")
    return info


def _group(names, count, matte):
    """The zip's frames of one folder: the matte's, or the result's (EXR), with as many frames as the plate."""
    groups = {}
    for n in sorted(names):
        if n.lower().endswith((".exr", ".png")) and ("matte" in n.lower()) == matte and (matte or n.lower().endswith(".exr")):
            groups.setdefault(os.path.dirname(n), []).append(n)
    found = [g for g in groups.values() if len(g) == count]
    if not found:
        raise SystemExit(f"No {'matte' if matte else 'result'} of {count} frames in the zip: {sorted(groups)}")
    return found[0]


def seam(plate: str, export: str, ring: int = 6, every: int = 4) -> dict:
    frames = plateio.find_sequence(plate)
    level, lums, untouched, top = [], [], 0.0, 0.0
    with zipfile.ZipFile(export) as z, tempfile.TemporaryDirectory() as tmp:
        results, mattes = _group(z.namelist(), len(frames), False), _group(z.namelist(), len(frames), True)
        for i in range(0, len(frames), every):
            p = plateio.read_float(frames[i])
            r = plateio.read_float(z.extract(results[i], tmp))
            m = plateio.read_float(z.extract(mattes[i], tmp))[..., 0]
            new = m >= NEW
            edge = new & ~ndimage.binary_erosion(new, iterations=ring)
            lp, lr = p @ LUMA, r @ LUMA
            keep = edge & (lp > BANDS[0][0]) & (lr > 0)
            level.append(np.log2(lr[keep] / lp[keep]))
            lums.append(lp[keep])
            out = plateio.untouched(m)
            untouched = max(untouched, float(np.abs(r[out] - p[out]).max(initial=0.0)))
            top = max(top, float(lp.max()))
    level, lums = np.concatenate(level), np.concatenate(lums)
    rows = []
    for lo, hi in BANDS:
        d = level[(lums >= lo) & (lums < hi)]
        rows.append((lo, hi, d.size, *(np.percentile(d, (50, 10, 90)) if d.size else (np.nan,) * 3)))
    lines = [f"# The seam of `{export}`", "",
             f"The result against the plate on the {ring} px of new pixels at the matte's edge (the matte at {NEW} or more), "
             f"on {len(range(0, len(frames), every))} of {len(frames)} frames. 0 stops is the plate's level.", "",
             "| Plate luminance | Pixels | Median, stops | 10th to 90th percentile, stops |", "| --- | --- | --- | --- |"]
    lines += [f"| {lo:g} to {hi:g} | {n} | {med:+.2f} | {p10:+.2f} to {p90:+.2f} |" for lo, hi, n, med, p10, p90 in rows]
    lines += ["", f"The plate's peak: {top:.2f}. Untouched pixels (the matte under one 8-bit step): the largest difference "
              f"from the plate is {untouched:.4f}."]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(os.path.dirname(os.path.abspath(export)), "seam.md"), "w") as f:
        f.write(text)
    print(text)
    return {"rows": rows, "untouched": untouched, "peak": top}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="what", required=True)
    m = sub.add_parser("make", help="the HDR plate from a movie")
    m.add_argument("--source", required=True)
    m.add_argument("--out", required=True, help="a folder in ComfyUI's input folder; the frames take its name")
    m.add_argument("--peak", type=float, default=7.0)
    m.add_argument("--frames", type=int, default=121)
    s = sub.add_parser("seam", help="the edit's level against the plate at the matte's edge")
    s.add_argument("--plate", required=True)
    s.add_argument("--export", required=True, help="the export.zip that tests/ui_live.py downloads")
    s.add_argument("--ring", type=int, default=6)
    s.add_argument("--every", type=int, default=4)
    a = ap.parse_args()
    make(a.source, a.out, a.peak, a.frames) if a.what == "make" else seam(a.plate, a.export, a.ring, a.every)
