"""Replay a recording of Follow Matte's inputs through mathops.follow_matte, on a CPU, and measure the matte.

ComfyUI started with PAINTAPLATE_RECORD=<folder> writes one .npz file per Follow Matte run (mathops.record): the
tracker's masks, the first-frame mask, the element, the shot, the plate and a Clean edit's matte, at the size Follow
Matte works at. This tool runs follow_matte again on such a file, with this checkout's mathops.py first, then with each
copy of mathops.py given by --code, and prints for each code the frames that hold a matte and the summary. Then one
table measures every code alike:
- the frames that hold a matte, by the plate's own numbers;
- the large changes kept: what the shot changed by Follow Matte's own test (mathops.shot_change above the threshold
  plus the frame's level, opened by one pixel), within one zone of the tracker's mask or of any code's matte, cut into
  connected pieces. The pieces of 64 px or more count: the share of their pixels inside the matte, as a mean over the
  frames that hold such pieces, and on the worst frame. A change that no code's matte follows, away from the
  tracker's mask, is not counted: this column reads with the frames that hold a matte;
- the matte's mean area, as a share of the frame;
- with --head, the share of the head inside the matte: the head is the top 45% and the right 30% of the box around
  the tracker's mask (a horse that faces right, whose whole body the tracker returns).
A line per code then says whether it gives this checkout's matte, pixel for pixel. With --sheet, a picture of four
frames (--frames, by the plate's own numbers): the plate, the shot, their difference 4 times brighter, and each code's
matte over the shot, its edge in yellow. A Clean's recording holds no shot: its sheet shows the plate. The tool needs
only the pack's own packages, so a recording replays on the machine that made it.

    python tests/matte_replay.py <recording.npz> [--code <copy of mathops.py>]... [--head]
        [--sheet <file.jpg>] [--frames 1,41,81,121] [--scale 0.5]
"""
import argparse
import importlib.util
import os
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mathops  # noqa: E402

LARGE = 64  # px: a changed piece this large is a change that the matte should keep; smaller ones are specks
GAIN = 4  # the sheet shows the difference between the shot and the plate this many times brighter
EIGHT = np.ones((3, 3), bool)


def code(path):
    """A copy of mathops.py loaded as a module of its own, with its name: its folder's when the file is mathops.py."""
    path = os.path.abspath(path)
    name = os.path.basename(os.path.dirname(path)) if os.path.basename(path) == "mathops.py" else os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(f"replayed_{len(sys.modules)}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return name, module


def runs(frames, first_frame):
    """Frame indices as the plate's numbers, in runs (« 1-42, 50 »), or « none »."""
    frames, out = [int(t) for t in frames], []
    for i, t in enumerate(frames):
        if i == 0 or t != frames[i - 1] + 1:
            start = t
        if i == len(frames) - 1 or frames[i + 1] != t + 1:
            out.append(f"{start + first_frame}" if start == t else f"{start + first_frame}-{t + first_frame}")
    return ", ".join(out) or "none"


def frame(stack, t, h, w):
    """Frame t of a stack (or its last frame), at h x w, its first three channels."""
    f = stack[min(t, len(stack) - 1)]
    return (f if f.shape[:2] == (h, w) else mathops.resize_to(f, h, w))[..., :3]


def measure(args, mattes, head=False):
    """The table's figures for each code's mattes ({name: (n, H, W)}) on one recording: {name: dict}."""
    n, shot, base, masks = args["n"], args["shot"], args["base"], args["masks"]
    h, w = mattes[next(iter(mattes))].shape[1:3]
    reach = max(2.0, args["zone"] * w)
    grow = lambda m, r: mathops.dilate(m.astype(np.uint8), r) > 0  # noqa: E731
    yy, xx = np.mgrid[:h, :w]
    held = {k: np.asarray(m) > 0.5 for k, m in mattes.items()}
    kept, heads = {k: [] for k in held}, {k: [] for k in held}
    for t in range(n):
        s = np.zeros((h, w), bool)
        if t < len(masks):
            s = (masks[t] if masks[t].shape == (h, w) else mathops.resize_to(masks[t].astype(np.float32), h, w)) > 0.5
        part = None
        if head and s.any():
            ys, xs = np.flatnonzero(s.any(1)), np.flatnonzero(s.any(0))
            part = s & (yy <= ys[0] + 0.45 * (ys[-1] - ys[0])) & (xx >= xs[0] + 0.7 * (xs[-1] - xs[0]))
        large = np.zeros((h, w), bool)
        anchor = s | np.any([m[t] for m in held.values()], axis=0)
        if shot is not None and anchor.any():
            d = mathops.shot_change(frame(shot, t, h, w), frame(base, t, h, w))
            within = grow(anchor, reach)
            around = grow(anchor, 3 * reach) & ~within
            level = float(np.median(d[around])) if int(around.sum()) >= 64 else 0.0
            labels, count = ndimage.label(ndimage.binary_opening(d > args["threshold"] + level, structure=EIGHT) & within, structure=EIGHT)
            large = (np.bincount(labels.ravel(), minlength=count + 1) >= LARGE)[labels] & (labels > 0)
        for k, m in held.items():
            if large.any():
                kept[k].append((float((large & m[t]).sum()) / float(large.sum()), t))
            if part is not None and part.any():
                heads[k].append((float((part & m[t]).sum()) / float(part.sum()), t))
    return {k: dict(frames=np.flatnonzero(m.reshape(n, -1).any(1)), area=float(m.mean()), kept=kept[k], head=heads[k]) for k, m in held.items()}


def share(pairs, first_frame, worst=min):
    """A mean share and its worst frame, as « 97.4% (80.1%, frame 63) »."""
    if not pairs:
        return "no such frame"
    low = worst(pairs)
    return f"{100 * np.mean([p for p, _ in pairs]):.1f}% ({100 * low[0]:.1f}%, frame {low[1] + first_frame})"


def sheet(path, args, mattes, numbers, scale):
    """The sheet: per frame, the plate, the shot, their difference GAIN times brighter, and each code's matte."""
    from PIL import Image, ImageDraw
    n, first, base = args["n"], args["first_frame"], args["base"]
    view = args["shot"] if args["shot"] is not None else base
    h, w = mattes[next(iter(mattes))].shape[1:3]
    cw, ch, top = max(1, round(w * scale)), max(1, round(h * scale)), 18
    names = ["plate", "shot" if args["shot"] is not None else "plate (a Clean: no shot)", f"difference x {GAIN}"] + [f"matte: {k}" for k in mattes]
    img = Image.new("RGB", (cw * len(names), top + ch * len(numbers)), (24, 24, 24))
    draw = ImageDraw.Draw(img)
    for i, name in enumerate(names):
        draw.text((i * cw + 4, 3), name, fill=(235, 235, 235))
    for r, number in enumerate(numbers):
        t = min(max(number - first, 0), n - 1)
        b, s = frame(base, t, h, w), frame(view, t, h, w)
        cells = [b, s, np.repeat(np.abs(s - b).max(-1, keepdims=True) * GAIN, 3, -1)]
        for m in mattes.values():
            held = np.asarray(m[t]) > 0.5
            cell = s * (0.3 + 0.7 * held[..., None])
            cell[held & ~ndimage.binary_erosion(held, iterations=max(1, round(1 / scale)))] = (1.0, 0.85, 0.1)
            cells.append(cell)
        for c, cell in enumerate(cells):
            img.paste(Image.fromarray((np.clip(cell, 0, 1) * 255).astype(np.uint8)).resize((cw, ch), Image.LANCZOS), (c * cw, top + r * ch))
        draw.text((4, top + r * ch + 4), f"frame {first + t}", fill=(255, 230, 0))
    img.save(path, quality=90)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("recording", help="a .npz file that PAINTAPLATE_RECORD wrote")
    ap.add_argument("--code", action="append", default=[], help="another copy of mathops.py to replay the recording with; named after its folder")
    ap.add_argument("--head", action="store_true", help="also measure the share of the head inside the matte")
    ap.add_argument("--sheet", default="", help="write the sheet to this file (.jpg or .png)")
    ap.add_argument("--frames", default="", help="the sheet's frames, by the plate's own numbers, with commas (by default the first, a third, two thirds, the last)")
    ap.add_argument("--scale", type=float, default=0.5, help="the sheet's cells against the recording's size")
    ap.add_argument("--workers", type=int, default=8, help="follow_matte's threads")
    a = ap.parse_args(argv)
    os.environ.pop("PAINTAPLATE_RECORD", None)  # a replay records nothing
    args = mathops.replay(a.recording)
    n, first = args["n"], args["first_frame"]
    mattes = {}
    for name, module in [("this checkout", mathops)] + [code(p) for p in a.code]:
        out, summary = module.follow_matte(**args, workers=a.workers)
        mattes[name] = np.asarray(out)
        frames = np.flatnonzero(mattes[name].reshape(n, -1).any(1))
        print(f"--- {name}: a matte on {len(frames)} of {n} frames ({runs(frames, first)})\n{summary}")
    h, w = mattes["this checkout"].shape[1:3]
    print(f"\n{os.path.basename(a.recording)}: {w} x {h}, {n} frames, zone {args['zone']:.4f} of the width, threshold {args['threshold']:g}; "
          f"large changes are pieces of {LARGE} px or more, within one zone of the tracker's mask or of a matte")
    results = measure(args, mattes, a.head)
    print("| Code | Frames with a matte | Large changes kept, mean (worst) | Matte area, mean |" + " Head in the matte, mean (worst) |" * a.head)
    print("| --- | --- | --- | --- |" + " --- |" * a.head)
    for k, r in results.items():
        print(f"| {k} | {len(r['frames'])} of {n}: {runs(r['frames'], first)} | {share(r['kept'], first) if args['shot'] is not None else 'a Clean: no shot'} "
              f"| {100 * r['area']:.2f}% of the frame |" + f" {share(r['head'], first, max)} |" * a.head)
    for k, m in mattes.items():
        if k != "this checkout":
            apart = (m != mattes["this checkout"]).reshape(n, -1).sum(1)
            print(f"{k}: the same matte as this checkout on every frame, pixel for pixel." if not apart.any() else
                  f"{k}: differs from this checkout on {int((apart > 0).sum())} frames, up to {int(apart.max())} px at frame {int(apart.argmax()) + first}.")
    if a.sheet:
        numbers = [int(x) for x in a.frames.split(",")] if a.frames else sorted({first + round(i * (n - 1) / 3) for i in range(4)})
        sheet(a.sheet, args, mattes, numbers, a.scale)
        print(f"sheet: {a.sheet}")


if __name__ == "__main__":
    main()
