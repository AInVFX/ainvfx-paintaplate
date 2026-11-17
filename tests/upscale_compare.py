"""Two measures of Upscale to 4K's results, on the machine that made them, for a report's sheets.

  seams   Runs of tests/upscale_plate.py --all on one shot, given by their labels. For each run, the change from one
          frame to the next (mean absolute difference over the frame's centre): a window's edge that jumps shows as a
          peak there. For each run after the first, its difference from the first, frame by frame. Centre crops of the
          frames around one edge, at 1:1, for a sheet.
          python tests/upscale_compare.py seams --comfy /workspace/ComfyUI --runs one win --edge 21 --out DIR
  colour  Runs made at an original's size from a smaller copy: the PSNR (peak signal-to-noise ratio) of each frame
          against the original, the mean difference of each channel, and centre crops of one frame, for a sheet.
          python tests/upscale_compare.py colour --comfy /workspace/ComfyUI --original PATH --runs lab none --out DIR
"""
import argparse
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
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.what == "seams":
        seams(a.comfy, a.runs, a.edge, a.out)
    else:
        colour(a.comfy, a.original, a.runs, a.out)
