"""Upscale to 4K on one window of a shot, as the page's Finish runs it, on a running ComfyUI: the seconds of the job and
of each node, the peaks of the GPU's memory and of ComfyUI's RAM, and the count and size of the frames it writes.

  python tests/upscale_plate.py --comfy /data/ComfyUI --shot plates/horse.mp4 --first 0 --count 42 --out ~/paintaplate_gpu/upscale

The shot is a movie or a frame sequence as Load Plate takes it. The target size is 3840 px on the long side with the
shot's aspect, in even numbers, or the shot's own size when it is larger. The frames land under ComfyUI's output folder
in <label>/upscale, and the report is <out>/<label>.md.
"""
import argparse
import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

LONG_SIDE = 3840


def target_size(width: int, height: int, long_side: int = LONG_SIDE) -> tuple:
    """`long_side` px on the long side with the shot's aspect, in even numbers; the shot's own size when it is larger."""
    if max(width, height) >= long_side:
        return width, height
    if width >= height:
        return long_side, 2 * round(long_side * height / width / 2)
    return 2 * round(long_side * width / height / 2), long_side


def values(shot: str, width: int, height: int, frames: int, label: str = "upscale", first: int = 0, count: int = 42,
           color_space: str = "@model", color_fix: str = "lab", fmt: str = "png16", seed: int = 42) -> dict:
    """The slots of the upscale workflow for one window of `frames` frames."""
    w, h = target_size(width, height)
    return {"shot": shot, "max_frames": frames, "first": first, "count": max(1, min(count, frames - first)), "width": w,
            "height": h, "color_space": color_space, "color_fix": color_fix, "format": fmt, "seed": seed,
            "prefix": f"{label}/upscale/f"}


def run(url: str, comfy: str, shot: str, out: str, label: str = "upscale", first: int = 0, count: int = 42,
        color_space: str = "@model", color_fix: str = "lab", fmt: str = "png16") -> dict:
    import build_workflows
    import plateio
    from hdr_plate import AFTER, BEFORE, _comfy_pid, _plate_info, node_rows, run_prompt
    full = os.path.join(comfy, "input", shot)
    if not os.path.exists(full):
        full = next(os.path.join(d, f) for d, _, fs in os.walk(comfy) for f in fs if f == os.path.basename(shot))
    w, h, n = _plate_info(full)
    v = values(shot, w, h, n, label, first, count, color_space, color_fix, fmt)
    prompt = build_workflows.fill("upscale", v)
    r = run_prompt(url, prompt, pid=_comfy_pid())
    files = sorted(glob.glob(os.path.join(comfy, "output", label, "upscale", "f_*")))
    size = None
    if files and files[0].endswith(".exr"):
        size = plateio.read_float(files[0]).shape[1::-1]
    elif files:  # a PNG's width and height follow its signature and the IHDR chunk's length and type
        with open(files[0], "rb") as f:
            size = struct.unpack(">II", f.read(24)[16:24])
    status = (r["history"].get("status") or {}).get("status_str", "no status")
    gb = lambda x: "not read" if x is None else f"{x:.1f} GB"  # noqa: E731
    lines = [f"# Upscale to 4K, one window: `{shot}`", "", "| | |", "| --- | --- |",
             f"| ComfyUI | {url}, job {r['job'][:8]}: {status} |",
             f"| Shot | {w} x {h}, {n} frames; window: frames {v['first'] + 1} to {v['first'] + v['count']} |",
             f"| Target | {v['width']} x {v['height']}, colour correction {color_fix}, {fmt} |",
             f"| Seconds | {r['seconds']:.1f} |", f"| Peak VRAM | {gb(r['peaks']['vram'])}, the GPU's memory in use |",
             f"| Peak RAM | {gb(r['peaks']['ram'])}, ComfyUI's process |",
             f"| Frames | {len(files)} files" + (f" at {size[0]} x {size[1]}" if size else "") + " |", "",
             "GB means 2^30 bytes.", "", "| Node | Seconds |", "| --- | --- |"]
    lines += [f"| {name} | {s:.1f} |" for name, s in node_rows(r["spent"], prompt)]
    text = "\n".join(lines) + "\n"
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"{label}.md"), "w") as f:
        f.write(text)
    print(text)
    by = sorted(((k, s) for k, s in r["spent"].items() if k not in (BEFORE, AFTER)), key=lambda kv: -kv[1])
    return {"seconds": r["seconds"], "frames": len(files), "size": size, "status": status, "by_node": by, "peaks": r["peaks"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--comfy", required=True, help="ComfyUI's folder: the shot under its input folder, the frames under its output folder")
    ap.add_argument("--shot", required=True, help="the shot as Load Plate takes it, such as plates/horse.mp4")
    ap.add_argument("--out", required=True, help="the folder of the report")
    ap.add_argument("--label", default="upscale", help="the report's name and the frames' folder under ComfyUI's output folder")
    ap.add_argument("--first", type=int, default=0, help="the window's first frame, from 0")
    ap.add_argument("--count", type=int, default=42, help="the window's frame count")
    ap.add_argument("--color-space", default="@model", help="the shot's file colour space in the OCIO config")
    ap.add_argument("--color-fix", default="lab", choices=("lab", "none"), help="SeedVR2's colour correction")
    ap.add_argument("--format", default="png16", choices=("png", "png16", "exr"))
    a = ap.parse_args()
    run(a.url, a.comfy, a.shot, os.path.expanduser(a.out), a.label, a.first, a.count, a.color_space, a.color_fix, a.format)
