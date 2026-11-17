"""Upscale to 4K on one window of a shot, as the page's Finish runs it, on a running ComfyUI: the seconds of the job and
of each node, the peaks of the GPU's memory and of ComfyUI's RAM, and the count and size of the frames it writes.

  python tests/upscale_plate.py --comfy /data/ComfyUI --shot plates/horse.mp4 --first 0 --count 21 --out ~/paintaplate_gpu/upscale
  python tests/upscale_plate.py --comfy /workspace/ComfyUI --shot plates/horse.mp4 --all --out /workspace/gpu/upscale

With --all, every window of the shot runs, then the upscale_export job writes the frames in the shot's own format.

The shot is a movie or a frame sequence as Load Plate takes it. The target size is 3840 px on the long side with the
shot's aspect, in even numbers, or the shot's own size when it is larger. The frames land under ComfyUI's output folder
in <label>/upscale and the export in <label>/export, and the report is <out>/<label>.md. The folder <label> under the
output folder is emptied first, since core's file counter goes on from the files in it.
"""
import argparse
import glob
import json
import os
import shutil
import struct
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

from build_workflows import UPSCALE_CHUNK, UPSCALE_OVERLAP  # noqa: E402

LONG_SIDE = 3840
FACTOR = 2  # SeedVR2 restores from at most the target divided by this
WINDOW = UPSCALE_CHUNK  # the smallest window: one chunk
MODEL_RAM = 15.7  # GB the 7B model holds in RAM on a GPU under 32 GB, where dynamic VRAM stages it
FRAME_COPIES = 12  # float32 copies of one frame at the target size that a window holds at its peak, colour correction
#                    included: a window of 42 frames at 3840 x 2160 past a 52 GB cap on a 16 GB GPU means more than 7.5
OUTPUT = "output:"  # folders.OUTPUT: a path under ComfyUI's output folder, as Load Plate reads it


def target_size(width: int, height: int, long_side: int = LONG_SIDE) -> tuple:
    """`long_side` px on the long side with the shot's aspect, in even numbers; the shot's own size when it is larger."""
    if max(width, height) >= long_side:
        return width, height
    if width >= height:
        return long_side, 2 * round(long_side * height / width / 2)
    return 2 * round(long_side * width / height / 2), long_side


def source_size(width: int, height: int, target: tuple) -> tuple:
    """The size SeedVR2 restores from: 0 x 0 (the shot as it is) when the target is FACTOR times its size or more, else
    the target divided by FACTOR, in even numbers."""
    if max(width, height) * FACTOR <= max(target):
        return 0, 0
    return 2 * round(target[0] / FACTOR / 2), 2 * round(target[1] / FACTOR / 2)


def windows(frames: int, first: int = 0, count: int = WINDOW, every: bool = False, overlap: int = UPSCALE_OVERLAP) -> list:
    """The windows to run, as (first, count): the one asked for, or with `every` the whole shot in windows of `count`
    frames, each sharing `overlap` frames with the one before."""
    if not every:
        return [(first, max(1, min(count, frames - first)))]
    out, start = [], 0
    while True:
        out.append((start, min(count, frames - start)))
        if start + count >= frames:
            return out
        start += count - overlap


def window_frames(ram_gb: float, vram_gb: float, target: tuple, plate: tuple, frames: int) -> int:
    """Frames per job on this machine: the whole shot when its RAM holds it, else the most that fit as 4n+1, at least one
    chunk. 90% of the RAM is used; the shot itself and 2 GB stay held, and the model too on a GPU under 32 GB."""
    held = (MODEL_RAM if vram_gb < 32 else 0.0) + 2.0 + frames * plate[0] * plate[1] * 12 / 2 ** 30
    fit = int((0.9 * ram_gb - held) / (FRAME_COPIES * target[0] * target[1] * 12 / 2 ** 30))
    if fit >= frames:
        return frames
    return max(WINDOW, fit - (fit - 1) % 4)


def machine(url: str) -> tuple:
    """(RAM, VRAM) in GB as the running ComfyUI reports them: its RAM under a cgroup's cap, its first GPU's memory."""
    with urllib.request.urlopen(f"{url}/system_stats", timeout=30) as r:
        stats = json.load(r)
    device = (stats.get("devices") or [{}])[0]
    return stats["system"]["ram_total"] / 2 ** 30, device.get("vram_total", 0) / 2 ** 30


def export_values(shot: str, frames: int, label: str = "upscale") -> dict:
    """The slots of the upscale_export workflow: the windows' frames, read under ComfyUI's output folder."""
    return {"shot": shot, "frames": f"{OUTPUT}{label}/upscale", "max_frames": frames, "prefix": f"{label}/export",
            "overlap": UPSCALE_OVERLAP}


def frame_size(path: str) -> tuple:
    """(width, height) of a PNG or EXR frame."""
    if path.endswith(".exr"):
        import plateio
        return plateio.read_float(path).shape[1::-1]
    with open(path, "rb") as f:  # a PNG's width and height follow its signature and the IHDR chunk's length and type
        return struct.unpack(">II", f.read(24)[16:24])


def values(shot: str, width: int, height: int, frames: int, label: str = "upscale", first: int = 0, count: int = WINDOW,
           color_space: str = "@model", color_fix: str = "lab", fmt: str = "png16", seed: int = 42, window: int = 0) -> dict:
    """The slots of the upscale workflow for window number `window` of a shot of `frames` frames: its own folder."""
    w, h = target_size(width, height)
    sw, sh = source_size(width, height, (w, h))
    return {"shot": shot, "max_frames": frames, "source_width": sw, "source_height": sh, "first": first, "count": max(1, min(count, frames - first)), "width": w,
            "height": h, "color_space": color_space, "color_fix": color_fix, "format": fmt, "seed": seed,
            "prefix": f"{label}/upscale/w{window:03}/f"}


def run(url: str, comfy: str, shot: str, out: str, label: str = "upscale", first: int = 0, count: int = WINDOW,
        every: bool = False, color_space: str = "@model", color_fix: str = "lab", fmt: str = "png16") -> dict:
    import build_workflows
    from hdr_plate import _comfy_pid, _plate_info, node_rows, run_prompt
    full = os.path.join(comfy, "input", shot)
    if not os.path.exists(full):
        full = next(os.path.join(d, f) for d, _, fs in os.walk(comfy) for f in fs if f == os.path.basename(shot))
    w, h, n = _plate_info(full)
    shutil.rmtree(os.path.join(comfy, "output", label), ignore_errors=True)
    target = target_size(w, h)
    count = count or window_frames(*machine(url), target, (w, h), n)
    jobs = [("upscale", values(shot, w, h, n, label, f, c, color_space, color_fix, fmt, window=k))
            for k, (f, c) in enumerate(windows(n, first, count, every))]
    if every:
        jobs.append(("upscale_export", export_values(shot, n, label)))
    gb = lambda x: "not read" if x is None else f"{x:.1f} GB"  # noqa: E731
    rows, nodes, seconds = [], [], []
    for name, v in jobs:
        prompt = build_workflows.fill(name, v)
        r = run_prompt(url, prompt, pid=_comfy_pid())
        status = (r["history"].get("status") or {}).get("status_str", "no status")
        what = f"frames {v['first'] + 1} to {v['first'] + v['count']}" if name == "upscale" else "the export"
        rows.append(f"| {name} | {what} | {status} | {r['seconds']:.1f} | {gb(r['peaks']['vram'])} | {gb(r['peaks']['ram'])} |")
        nodes += [f"| {name}, {what} | {node} | {s:.1f} |" for node, s in node_rows(r["spent"], prompt)]
        seconds.append(r["seconds"])
    files = sorted(glob.glob(os.path.join(comfy, "output", label, "upscale", "w*", "f_*")))
    size = frame_size(files[0]) if files else None
    v = jobs[0][1]
    lines = [f"# Upscale to 4K: `{shot}`", "", "| | |", "| --- | --- |", f"| ComfyUI | {url} |",
             f"| Shot | {w} x {h}, {n} frames; {len(jobs) - every} " + ("window" if len(jobs) - every == 1 else "windows")
             + f" of up to {count} frames" + (f", sharing {UPSCALE_OVERLAP} frames" if len(jobs) - every > 1 else "") + " |",
             f"| Target | {v['width']} x {v['height']}, from " + (f"{v['source_width']} x {v['source_height']}" if v["source_width"] else "the shot's size")
             + f", colour correction {color_fix}, {fmt} |",
             f"| Frames | {len(files)} files" + (f" at {size[0]} x {size[1]}" if size else "") + " |"]
    if every:
        exported = sorted(os.listdir(os.path.join(comfy, "output", label, "export"))) if os.path.isdir(os.path.join(comfy, "output", label, "export")) else []
        lines.append(f"| Export | {len(exported)} files: " + (", ".join(exported[:3]) or "none") + " |")
    lines += [f"| Seconds | {sum(seconds):.1f} in all |", "", "| Job | Window | Status | Seconds | Peak VRAM | Peak RAM |",
              "| --- | --- | --- | --- | --- | --- |", *rows, "", "GB means 2^30 bytes. Peak RAM is ComfyUI's process.", "",
              "| Job | Node | Seconds |", "| --- | --- | --- |", *nodes]
    text = "\n".join(lines) + "\n"
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"{label}.md"), "w") as f:
        f.write(text)
    print(text)
    return {"seconds": seconds, "frames": len(files), "size": size, "rows": rows}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--comfy", required=True, help="ComfyUI's folder: the shot under its input folder, the frames under its output folder")
    ap.add_argument("--shot", required=True, help="the shot as Load Plate takes it, such as plates/horse.mp4")
    ap.add_argument("--out", required=True, help="the folder of the report")
    ap.add_argument("--label", default="upscale", help="the report's name and the frames' folder under ComfyUI's output folder")
    ap.add_argument("--first", type=int, default=0, help="the window's first frame, from 0")
    ap.add_argument("--count", type=int, default=0, help="the window's frame count; 0 sizes it to the machine's RAM and GPU")
    ap.add_argument("--all", action="store_true", help="every window of the shot, then the export in the shot's own format")
    ap.add_argument("--color-space", default="@model", help="the shot's file colour space in the OCIO config")
    ap.add_argument("--color-fix", default="lab", choices=("lab", "none"), help="SeedVR2's colour correction")
    ap.add_argument("--format", default="png16", choices=("png", "png16", "exr"))
    a = ap.parse_args()
    run(a.url, a.comfy, a.shot, os.path.expanduser(a.out), a.label, a.first, a.count, a.all, a.color_space, a.color_fix, a.format)
