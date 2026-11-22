"""Measure any function that makes a matte, on recordings of Follow Matte, against references drawn by hand.

A recording is a file that PAINTAPLATE_RECORD wrote (mathops.record). Beside it, a study can keep two files:
- <recording>.tracks.npz: more tracks of SAM 3.1 on the same frames, one array (N, H, W) per name, in 0 to 1 or in
  8 bits, such as the element tracked on the shot or the paint zone tracked on the plate;
- <recording>.json: what the recording does not hold, such as the case's name ("case") and the edit's caption.
A reference is the matte that a careful person draws on one frame: <refs>/<case>/ref_<frame>.png, grey, 8 bits, at any
size (it is read at the recording's size): 255 where the edit acts, 0 where the plate must stay, and values between for
what is partly transparent, such as thin smoke. <frame> is the plate's own number. <case> is the recording's "case",
else the name of its folder.

An approach is a function approach(rec) -> mattes (N, H, W) in 0 to 1, named as file.py:function. `rec` holds
mathops.replay(recording), with `tracks`, `facts` (the .json) and `path` added. A matte of another size is resampled to
the recording's size, and a shorter one holds its last frame. `baseline` is this checkout's follow_matte; each --code
adds follow_matte from another copy of mathops.py, named after its folder.

Each recording gets one table, where every approach is measured alike:
- the edit lost: on each reference frame, the share of the reference that the matte misses, sum(max(ref - matte, 0))
  / sum(ref); the plate lost: the matte where the reference holds none, sum(max(matte - ref, 0)) / sum(ref). Both are
  shares of the reference's area: a matte twice the object's size loses 100% of plate. A band of --band px on each
  side of the reference's edge (where it crosses 0.5) counts for neither, as a careful person and a matte can place
  one edge a pixel or two apart, and the composite feathers it. Each column gives the mean over the reference frames,
  then the worst frame. « Plate lost, seen » weights the plate lost by how far the shot differs from the plate there
  (mathops.shot_change against the recording's threshold, full weight from the threshold up): taking the shot where it
  reproduces the plate costs nothing visible. A Clean's recording holds no shot: its weight comes from the clean plate
  pass, in the Fit to Plate recording of the same frames beside it; without one, the column is empty. On a frame whose
  reference holds nothing (the object hidden or gone), « where none » gives the matte's area there, as a share of the
  frame;
- the measures of tests/matte_replay.py: the frames that hold a matte, the large changes kept, the mean area and, with
  --head, the share of the head of a horse that faces right;
- the flicker (mathops.matte_flicker): the share of the matte that comes and goes within 3 frames, the mean over the
  frames, then the worst frame;
- the approach's seconds on this machine.
A row whose mean edit lost or mean plate lost is more than --worse points above the first approach's (--first) reads
« worse ». The study writes study.md, study.json and, with --sheet, one picture per recording: on each reference frame
(or on the frames of mathops.reference_frames when there are none), the plate, the shot, the reference over the shot,
then each approach's matte over the shot, with the plate lost in red, the edit lost in blue and the matte's edge in
yellow. A Clean's recording holds no shot: its pictures show the plate.

    python tests/matte_study.py <recording.npz>... [--refs <folder>] [--approach file.py:function]...
        [--code <copy of mathops.py>]... [--first baseline] [--band 2] [--worse 0.5] [--head]
        [--out <folder>] [--sheet] [--scale 0.5]
"""
import argparse
import glob
import importlib.util
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import mathops  # noqa: E402
import matte_replay  # noqa: E402

BAND = 2  # px at the recording's size, on each side of a reference's edge, that count for neither measure
WORSE = 0.5  # points: a mean edit lost or plate lost this far above the first approach's reads « worse »


def beside(path, suffix):
    """A study's file beside a recording: the recording's path without .npz, then `suffix`."""
    return os.path.splitext(path)[0] + suffix


def load(path):
    """(follow_matte's arguments, rec) for one recording: rec is what an approach reads."""
    args = mathops.replay(path)
    tracks = {}
    if os.path.exists(beside(path, ".tracks.npz")):
        with np.load(beside(path, ".tracks.npz")) as d:
            tracks = {k: d[k].astype(np.float32) / (255.0 if d[k].dtype == np.uint8 else 1.0) for k in d.files}
    clean = None
    if args["shot"] is None:  # a Clean: the clean plate pass, from the Fit to Plate recording of the same frames
        fits = [f for f in glob.glob(os.path.join(os.path.dirname(path), "fit_to_plate_*.npz")) if f"_{args['n']}f_" in os.path.basename(f)]
        if fits:
            fit = mathops.replay_fit(max(fits, key=os.path.getsize))
            h, w = args["base"].shape[1:3]
            clean = np.stack([f if f.shape[:2] == (h, w) else mathops.resize_to(f, h, w) for f in fit["image"]])
    facts = {}
    if os.path.exists(beside(path, ".json")):
        with open(beside(path, ".json"), encoding="utf-8") as f:
            facts = json.load(f)
    return args, dict(args, tracks=tracks, facts=facts, path=path, clean=clean)


def size(args):
    """The recording's (N, H, W): Follow Matte's size, the shot's or else the first-frame mask's."""
    for k in ("shot", "base", "first"):
        if args.get(k) is not None:
            return args["n"], args[k].shape[-3 if k != "first" else -2], args[k].shape[-2 if k != "first" else -1]
    return args["n"], args["masks"].shape[-2], args["masks"].shape[-1]


def approaches(specs, codes):
    """[(name, run(args, rec) -> mattes)]: baseline, each --code's follow_matte, then each --approach."""
    out = [("baseline", lambda args, rec: mathops.follow_matte(**args)[0])]
    for c in codes:
        name, module = matte_replay.code(c)
        out.append((name, lambda args, rec, m=module: m.follow_matte(**args)[0]))
    for spec in specs:
        file, _, fn = spec.rpartition(":")
        if not file or not fn:
            raise SystemExit(f"--approach {spec}: give it as file.py:function")
        loader = importlib.util.spec_from_file_location(f"approach_{len(sys.modules)}", os.path.abspath(file))
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        name = fn if fn not in [n for n, _ in out] else f"{os.path.splitext(os.path.basename(file))[0]}.{fn}"
        out.append((name, lambda args, rec, f=getattr(module, fn): f(rec)))
    return out


def fitted(mattes, n, h, w):
    """An approach's mattes as (n, h, w) half floats in 0 to 1: resampled, and held on their last frame when short."""
    m = np.asarray(mattes, np.float32)
    if m.ndim == 2:
        m = m[None]
    if m.shape[1:] != (h, w):
        m = np.stack([mathops.resize_to(f, h, w) for f in m])
    if len(m) < n:
        m = np.concatenate([m, np.repeat(m[-1:], n - len(m), 0)]) if len(m) else np.zeros((n, h, w), np.float32)
    return m[:n].clip(0, 1).astype(np.float16)


def references(folder, case, n, h, w, first_frame):
    """{frame index: (h, w) reference in 0 to 1} from <folder>/<case>/ref_<plate frame>.png."""
    out, d = {}, os.path.join(folder, case) if folder else ""
    if not d or not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        stem, ext = os.path.splitext(name)
        if not stem.startswith("ref_") or ext.lower() != ".png" or not stem[4:].isdigit():
            continue
        t = int(stem[4:]) - first_frame
        if 0 <= t < n:
            with Image.open(os.path.join(d, name)) as im:
                r = np.asarray(im.convert("L"), np.float32) / 255.0
            out[t] = r if r.shape == (h, w) else mathops.resize_to(r, h, w)
    return out


def counted(ref, band):
    """Where a frame counts: everywhere but --band px on each side of the reference's edge."""
    edge = ref > 0.5
    if band <= 0 or not edge.any() or edge.all():
        return np.ones(ref.shape, bool)
    return (ndimage.distance_transform_edt(edge) > band) | (ndimage.distance_transform_edt(~edge) > band)


def score(matte, ref, band, seen=None):
    """(edit lost, plate lost, where none, plate lost seen) on one frame. Edit lost and plate lost are shares of the
    reference's area, or None when the reference holds nothing; where none is then the matte's area as a share of the
    frame, else None. Plate lost seen weights the plate lost by `seen` (0 to 1 per pixel), or is None without it."""
    matte = np.asarray(matte, np.float32)
    count = counted(ref, band)
    total = float(ref[count].sum())
    if total < 1.0:  # nothing to take on this frame: an object hidden or gone
        return None, None, float((matte > 0.5).mean()), None
    lost = np.maximum(matte - ref, 0)[count]
    return (float(np.maximum(ref - matte, 0)[count].sum()) / total, float(lost.sum()) / total, None,
            None if seen is None else float((lost * seen[count]).sum()) / total)


def seen_weight(args, t, clean=None):
    """How visible taking the shot is on frame t, per pixel: how far the shot (a Clean: its clean plate pass, `clean`)
    differs from the plate, against the threshold, from 0 to 1. None without a shot or a clean plate pass."""
    view = args["shot"] if args["shot"] is not None else clean
    if view is None:
        return None
    n, h, w = size(args)
    d = mathops.shot_change(np.asarray(matte_replay.frame(view, t, h, w), np.float32), np.asarray(matte_replay.frame(args["base"], t, h, w), np.float32))
    return np.clip(d / args["threshold"], 0, 1)


def mean_worst(pairs, first_frame, worst=max):
    """(mean, worst value, its plate frame) of [(value, frame index)], or None when empty."""
    pairs = [(v, t) for v, t in pairs if v is not None]
    if not pairs:
        return None
    v, t = worst(pairs)
    return float(np.mean([p for p, _ in pairs])), float(v), int(t) + first_frame


def measure(args, rec, runs, refs, band, head):
    """{name: figures} for every approach on one recording."""
    first_frame = args["first_frame"]
    mattes = {name: m for name, (m, _) in runs.items()}
    replayed = matte_replay.measure(args, mattes, head=head)
    weights = {t: seen_weight(args, t, rec.get("clean")) for t in refs}
    out = {}
    for name, (m, seconds) in runs.items():
        scores = {t: score(m[t], r, band, weights[t]) for t, r in refs.items()}
        flicker = mathops.matte_flicker(m)
        out[name] = {
            "edit_lost": mean_worst([(s[0], t) for t, s in scores.items()], first_frame),
            "plate_lost": mean_worst([(s[1], t) for t, s in scores.items()], first_frame),
            "where_none": mean_worst([(s[2], t) for t, s in scores.items()], first_frame),
            "plate_seen": mean_worst([(s[3], t) for t, s in scores.items()], first_frame),
            "frames": int(len(replayed[name]["frames"])),
            "kept": mean_worst(replayed[name]["kept"], first_frame, worst=min),
            "head": mean_worst(replayed[name]["head"], first_frame),
            "area": replayed[name]["area"],
            "flicker": mean_worst([(float(v), t) for t, v in enumerate(flicker)], first_frame),
            "seconds": seconds,
            "per_frame": {str(t + first_frame): {"edit_lost": s[0], "plate_lost": s[1], "where_none": s[2], "plate_seen": s[3]} for t, s in scores.items()},
        }
    return out


def cell(fig, percent=True):
    """One figure as the table writes it: « mean (worst, frame N) »."""
    if fig is None:
        return "-"
    k = 100 if percent else 1
    return f"{k * fig[0]:.1f}% ({k * fig[1]:.1f}%, frame {fig[2]})"


def worse(fig, base, by):
    """Whether a mean is more than `by` points above the first approach's."""
    return fig is not None and base is not None and 100 * (fig[0] - base[0]) > by


def table(case, path, args, figures, refs, first, by, head):
    """The recording's table, in Markdown."""
    n, h, w = size(args)
    frames = ", ".join(str(t + args["first_frame"]) for t in sorted(refs)) or "none"
    lines = [f"### {case} · {os.path.basename(path)} · {w} x {h}, {n} frames, references on frames {frames}", "",
             "| Approach | Edit lost | Plate lost | Plate lost, seen | Where none | Frames with a matte | Large changes kept | Mean area | Flicker |"
             + (" Head |" if head else "") + " Seconds | |",
             "| --- " * (10 + head) + "| --- |"]
    base = figures.get(first, {})
    for name, f in figures.items():
        mark = "worse" if name != first and (worse(f["edit_lost"], base.get("edit_lost"), by) or worse(f["plate_lost"], base.get("plate_lost"), by)) else ""
        lines.append(f"| {name} | {cell(f['edit_lost'])} | {cell(f['plate_lost'])} | {cell(f['plate_seen'])} | {cell(f['where_none'])} | {f['frames']} | {cell(f['kept'])} "
                     f"| {100 * f['area']:.2f}% | {cell(f['flicker'])} |" + (f" {cell(f['head'])} |" if head else "") + f" {f['seconds']:.1f} | {mark} |")
    return "\n".join(lines) + "\n"


def font(px):
    """A font for the sheet's labels, at `px` pixels where Pillow can scale its own."""
    try:
        return ImageFont.load_default(size=px)
    except TypeError:  # an older Pillow: its one bitmap size
        return ImageFont.load_default()


def picture(img):
    """An (H, W, 3) frame in 0 to 1 as 8 bits."""
    return (np.asarray(img, np.float32).clip(0, 1) * 255 + 0.5).astype(np.uint8)


def sheet(path, args, runs, refs, band, scale):
    """One picture of the recording: a row per reference frame, the plate, the shot, the reference, then each approach."""
    n, h, w = size(args)
    plate = args["base"] if args["base"] is not None else args["shot"]
    view = args["shot"] if args["shot"] is not None else plate
    frames = sorted(refs) or mathops.reference_frames(n)
    names = ["plate", "shot", "reference"] + list(runs)
    cw, ch, top, left = max(1, round(w * scale)), max(1, round(h * scale)), 28, 90
    out = Image.new("RGB", (left + cw * len(names), top + ch * len(frames)), (24, 24, 24))
    draw, label = ImageDraw.Draw(out), font(16)
    for j, name in enumerate(names):
        draw.text((left + j * cw + 6, 6), name, fill=(235, 235, 235), font=label)
    for i, t in enumerate(frames):
        draw.text((6, top + i * ch + 6), f"frame {t + args['first_frame']}", fill=(235, 235, 235), font=label)
        p = np.asarray(matte_replay.frame(plate, t, h, w), np.float32) if plate is not None else np.zeros((h, w, 3), np.float32)
        s = np.asarray(matte_replay.frame(view, t, h, w), np.float32) if view is not None else p
        r = refs.get(t)
        cells = [picture(p), picture(s)]
        if r is None:
            cells.append(picture(s * 0.35))
        else:
            edge = (r > 0.5) ^ ndimage.binary_erosion(r > 0.5)
            c = s * (0.45 + 0.55 * r[..., None]) * np.array([0.8, 1.0, 0.8], np.float32)
            c[edge] = (1.0, 0.9, 0.1)
            cells.append(picture(c))
        for m, _ in runs.values():
            mt = np.asarray(m[t], np.float32)
            c = s * (0.35 + 0.65 * mt[..., None])
            if r is not None:
                count = counted(r, band)
                c[(mt - r > 0.5) & count] = (0.95, 0.15, 0.15)  # plate lost
                c[(r - mt > 0.5) & count] = (0.2, 0.45, 1.0)  # edit lost
            c[(mt > 0.5) ^ ndimage.binary_erosion(mt > 0.5)] = (1.0, 0.9, 0.1)
            cells.append(picture(c))
        for j, c in enumerate(cells):
            out.paste(Image.fromarray(c).resize((cw, ch), Image.LANCZOS), (left + j * cw, top + i * ch))
    out.save(path, quality=92)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("recordings", nargs="+", help="files that PAINTAPLATE_RECORD wrote (follow_matte_*.npz)")
    ap.add_argument("--refs", default="", help="the references' folder: <refs>/<case>/ref_<frame>.png")
    ap.add_argument("--approach", action="append", default=[], help="file.py:function, called as function(rec)")
    ap.add_argument("--code", action="append", default=[], help="a copy of mathops.py whose follow_matte is measured too")
    ap.add_argument("--first", default="baseline", help="the approach the others are compared with")
    ap.add_argument("--band", type=float, default=BAND, help="px on each side of a reference's edge that count for neither measure")
    ap.add_argument("--worse", type=float, default=WORSE, help="points above the first approach's mean that read « worse »")
    ap.add_argument("--head", action="store_true", help="also the share of the head of a horse that faces right")
    ap.add_argument("--out", default=".", help="the folder for study.md, study.json and the sheets")
    ap.add_argument("--sheet", action="store_true", help="one picture per recording")
    ap.add_argument("--scale", type=float, default=0.5, help="the sheet's size against the recording's")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    found, text = {}, ["# Matte study", ""]
    for path in a.recordings:
        args, rec = load(path)
        n, h, w = size(args)
        case = rec["facts"].get("case") or os.path.basename(os.path.dirname(os.path.abspath(path)))
        refs = references(a.refs, case, n, h, w, args["first_frame"])
        runs = {}
        for name, run in approaches(a.approach, a.code):
            start = time.perf_counter()
            m = fitted(run(args, rec), n, h, w)
            runs[name] = (m, time.perf_counter() - start)
        figures = measure(args, rec, runs, refs, a.band, a.head)
        key = f"{case}/{os.path.basename(path)}"
        found[key] = figures
        text.append(table(case, path, args, figures, refs, a.first, a.worse, a.head))
        if a.sheet:
            sheet(os.path.join(a.out, f"sheet_{case}_{os.path.splitext(os.path.basename(path))[0]}.jpg"), args, runs, refs, a.band, a.scale)
    with open(os.path.join(a.out, "study.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(text))
    with open(os.path.join(a.out, "study.json"), "w", encoding="utf-8") as f:
        json.dump(found, f, indent=1)
    print("\n".join(text))
    return found


if __name__ == "__main__":
    main()
