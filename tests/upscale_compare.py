"""Two measures of Upscale's results, on the machine that made them, for a report's sheets.

  seams   Runs of tests/upscale_plate.py --all on one shot, given by their labels. For each run, the change from one
          frame to the next (mean absolute difference over the frame's centre): a window's edge that jumps shows as a
          peak there. For each run after the first, its difference from the first, frame by frame. Centre crops of the
          frames around one edge, at 1:1, for a sheet.
          python tests/upscale_compare.py seams --comfy /workspace/ComfyUI --runs one win --edge 21 --out DIR
  colour  Runs made at an original's size from a smaller copy: the PSNR (peak signal-to-noise ratio) of each frame
          against the original, the mean difference of each channel, and centre crops of one frame, for a sheet.
          python tests/upscale_compare.py colour --comfy /workspace/ComfyUI --original PATH --runs lab none --out DIR
  crops   One frame of several results (--result label=folder, once for each), the same box (--box X Y W H) of each
          at full size, side by side with its label: the sheet of a half against a third.
  parts   The upscaled set of one export (upscaled/ of its zip, unpacked, or of the render's folder): for each frame, how far the upscaled
          result is from upscaled plate x (1 - upscaled matte) + upscaled layer x upscaled matte (the mean and the largest difference, and the
          share of pixels more than 2 steps off, in 8-bit steps), and crops at 1:1 along the matte's edge on a few frames:
          the result, the plate, the layer and the difference ten times brighter, one row per frame, for a sheet.
          python tests/upscale_compare.py parts --set DIR/upscaled --frames 1 61 121 --out DIR
"""
import argparse
import itertools
import csv
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plateio  # noqa: E402


def frames_of(comfy: str, label: str) -> np.ndarray:
    """A run's frames, its windows joined as the export joins them."""
    return plateio.join_windows(sorted(glob.glob(os.path.join(comfy, "output", label, "upscale", "w*"))))


def centre(a: np.ndarray, width: int, height: int) -> np.ndarray:
    h, w = a.shape[-3], a.shape[-2]
    y, x = max(0, (h - height) // 2), max(0, (w - width) // 2)
    return a[..., y:y + height, x:x + width, :]


def steps(frames: np.ndarray) -> list:
    """Mean absolute difference from each frame to the next."""
    return [float(np.abs(frames[t + 1] - frames[t]).mean()) for t in range(len(frames) - 1)]


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(((a.astype(np.float64) - b) ** 2).mean())
    return float("inf") if mse == 0 else float(10 * np.log10(1.0 / mse))


def png8(a: np.ndarray, path: str) -> None:
    from PIL import Image
    Image.fromarray(np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)).save(path)


def write_csv(path: str, columns: dict) -> None:
    n = max(len(v) for v in columns.values())
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", *columns])
        for t in range(n):
            w.writerow([t + 1, *[("%.6f" % v[t]) if t < len(v) else "" for v in columns.values()]])


def seams(comfy: str, runs: list, edge: int, out: str, crop: int = 640) -> dict:
    columns, first = {}, None
    for label in runs:
        frames = frames_of(comfy, label)
        middle = centre(frames, 1920, 1080)
        columns[f"{label} step"] = steps(middle)
        if first is None:
            first = (label, middle.copy())
        else:
            columns[f"{label} from {first[0]}"] = [float(np.abs(middle[t] - first[1][t]).mean()) for t in range(len(middle))]
        for t in range(edge - 2, edge + 2):
            png8(centre(frames[t], crop, crop), os.path.join(out, f"seam_{label}_f{t + 1:03}.png"))
        del frames, middle
    write_csv(os.path.join(out, "seams.csv"), columns)
    return columns


def colour(comfy: str, original: str, runs: list, out: str, frame: int = 61, crop: int = 480) -> dict:
    spec = plateio.probe_plate(original)
    orig = plateio.decode_video(original, 1024, spec["fps"])[0]
    png8(centre(orig[frame - 1], crop, crop), os.path.join(out, f"colour_original_f{frame:03}.png"))
    columns, lines = {}, []
    for label in runs:
        frames = frames_of(comfy, label)
        n = min(len(frames), len(orig))
        columns[f"{label} PSNR"] = [psnr(frames[t], orig[t]) for t in range(n)]
        shift = [float((frames[:n, ..., c] - orig[:n, ..., c]).mean()) for c in range(3)]
        lines.append(f"{label}: PSNR {np.mean(columns[label + ' PSNR']):.2f} dB on average; frames 1, 61, 121: "
                     + ", ".join(f"{columns[label + ' PSNR'][t]:.2f}" for t in (0, 60, n - 1) if t < n)
                     + f" dB; mean difference R, G, B: {shift[0]:+.4f}, {shift[1]:+.4f}, {shift[2]:+.4f}")
        png8(centre(frames[frame - 1], crop, crop), os.path.join(out, f"colour_{label}_f{frame:03}.png"))
        del frames
    write_csv(os.path.join(out, "colour.csv"), columns)
    with open(os.path.join(out, "colour.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return columns


MOVIES = (".mp4", ".mov", ".mkv", ".webm", ".mxf")


def part_frames(path: str):
    """The frames of one part of the upscaled set, one at a time, as float32 RGB: its movie, or its folder of frames."""
    names = sorted(os.listdir(path))
    movies = [n for n in names if n.lower().endswith(MOVIES)]
    if movies:
        import av
        with av.open(os.path.join(path, movies[0])) as c:
            stream = c.streams.video[0]
            fmt, top = ("rgb24", 255.0) if plateio.eight_bit_rgb(stream.pix_fmt) else ("rgb48le", 65535.0)
            for frame in c.decode(stream):
                yield frame.to_ndarray(format=fmt).astype(np.float32) / top
        return
    for n in names:
        if n.lower().endswith((".png", ".exr", ".tif", ".tiff", ".dpx")):
            yield plateio.read_float(os.path.join(path, n))[..., :3]


def parts(root: str, out: str, frames=(1, 61, 121), crop: int = 480) -> dict:
    """See the module's docstring. `root` holds export/, plate/, layer/ and matte/."""
    columns, rows = {"frame": [], "mean": [], "max": [], "over2": []}, []
    for i, (res, plate, layer, matte) in enumerate(zip(*(part_frames(os.path.join(root, n)) for n in ("export", "plate", "layer", "matte"))), 1):
        m = matte[..., :1]
        diff = np.abs(res - (plate * (1 - m) + layer * m)) * 255
        for key, value in (("frame", i), ("mean", float(diff.mean())), ("max", float(diff.max())), ("over2", float((diff > 2).mean()))):
            columns[key].append(value)
        if i in frames:  # around the middle of the matte's soft edge, or the frame's centre when it has none
            edge = np.argwhere((m[..., 0] > 0.1) & (m[..., 0] < 0.9))
            cy, cx = edge.mean(0).astype(int) if len(edge) else (res.shape[0] // 2, res.shape[1] // 2)
            y, x = max(0, min(cy - crop // 2, res.shape[0] - crop)), max(0, min(cx - crop // 2, res.shape[1] - crop))
            rows.append(np.concatenate([a[y:y + crop, x:x + crop] for a in (res, plate, layer, np.clip(diff * 10 / 255, 0, 1))], axis=1))
    write_csv(os.path.join(out, "parts.csv"), columns)
    if rows:
        png8(np.concatenate(rows, axis=0), os.path.join(out, "parts_sheet.png"))
    return {"frames": len(columns["frame"]), "mean": float(np.mean(columns["mean"])) if rows or columns["mean"] else 0.0,
            "max": max(columns["max"], default=0.0), "over2": max(columns["over2"], default=0.0)}


def crops(results: list, frame: int, box: tuple, out: str) -> str:
    """The same frame of several results, the same box of each at full size, side by side with its label, in one PNG.
    `results`: (label, folder) pairs, a folder of frames or a movie's folder, all at one size; `frame` from 1; `box`: x, y,
    width and height in px."""
    from PIL import Image, ImageDraw
    x, y, w, h = box
    tiles = []
    for label, path in results:
        f = next(itertools.islice(part_frames(path), frame - 1, None))
        tile = Image.fromarray((np.clip(f[y:y + h, x:x + w, :3], 0, 1) * 255 + 0.5).astype(np.uint8))
        ImageDraw.Draw(tile).text((12, 10), label, fill=(255, 190, 0))
        tiles.append(tile)
    sheet = Image.new("RGB", (w * len(tiles) + 8 * (len(tiles) - 1), h))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (i * (w + 8), 0))
    name = os.path.join(out, f"crops_f{frame}.png")
    sheet.save(name)
    return name


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="what", required=True)
    s = sub.add_parser("seams")
    s.add_argument("--comfy", required=True)
    s.add_argument("--runs", nargs="+", required=True, help="the runs' labels, the first one the reference")
    s.add_argument("--edge", type=int, default=21, help="the last frame of the first window, from 1")
    s.add_argument("--out", required=True)
    c = sub.add_parser("colour")
    c.add_argument("--comfy", required=True)
    c.add_argument("--original", required=True)
    c.add_argument("--runs", nargs="+", required=True)
    c.add_argument("--out", required=True)
    p = sub.add_parser("parts")
    p.add_argument("--set", required=True, help="the upscaled set's folder, with export/, plate/, layer/ and matte/")
    p.add_argument("--frames", type=int, nargs="+", default=[1, 61, 121], help="the frames of the sheet, from 1")
    p.add_argument("--out", required=True)
    k = sub.add_parser("crops")
    k.add_argument("--result", action="append", required=True, help="label=folder: a result's frames or its movie's folder, once for each")
    k.add_argument("--frame", type=int, default=61, help="the frame, from 1")
    k.add_argument("--box", type=int, nargs=4, required=True, metavar=("X", "Y", "W", "H"), help="the box in px")
    k.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.what == "seams":
        seams(a.comfy, a.runs, a.edge, a.out)
    elif a.what == "crops":
        print(crops([r.split("=", 1) for r in a.result], a.frame, tuple(a.box), a.out))
    elif a.what == "parts":
        print(parts(a.set, a.out, tuple(a.frames)))
    else:
        colour(a.comfy, a.original, a.runs, a.out)
