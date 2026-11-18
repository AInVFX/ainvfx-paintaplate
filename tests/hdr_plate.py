"""An HDR test plate made from an SDR movie, and the level of an edit against it at the seam: a local proof that the
way back from the model space keeps the plate's levels (PLA), without a pod.

  make  The movie becomes half-float EXR frames in scene-linear Rec.709, lifted by the inverse of core's tone mapping to
        a peak near `--peak`. The models then see the movie as it was, so the same seed and strokes make the edit of the
        SDR case, and two runs differ only by the way back to the plate.
  seam  In the export's zip: the result against the plate on the ring of new pixels at the matte's edge, by the plate's
        luminance. The median level in stops: 0 is the plate's level. It also checks that the untouched pixels are the
        plate's. Written to seam.md beside the zip.
  groups  Each frame folder in the export's zip with its file count and, for a folder of EXR frames as many as the plate's,
        the largest difference from the plate where the delivered matte shows 0. The export copies those pixels exactly;
        a folder that blends there is not the export.
  bands  Where the tiles of a tiled decode show: its frames against the same latent decoded whole, by column and by row,
        in stops (log2 of the ratio of the channels' mean) or, with --steps, in 8-bit steps for display frames. For each
        band where two tiles blend, how far the difference swings across it: a decode with no band reads 0 everywhere.
        Two runs of finish that differ only by --tile decode the same latent, since ComfyUI keeps the first run's results
        and runs again only the decode and the nodes after it.
        python tests/hdr_plate.py bands --ref /data/ComfyUI/output/whole/hdr --test /data/ComfyUI/output/t256/hdr --tile 256 --work 1920x1088
  finish  SDR to HDR on a plate with no edit, as the page's Finish runs it, on a running ComfyUI: the seconds of the job
        and of each node, the peaks of the GPU's memory and of ComfyUI's RAM, and the HDR frames' count and size.
        python tests/hdr_plate.py finish --comfy /data/ComfyUI --plate plates/horse.mp4 --out ~/paintaplate_gpu/w9_plate

With ComfyUI's Python (numpy, scipy, av, OpenEXR), no GPU, on any version of the pack:
  python tests/hdr_plate.py make --source /data/ComfyUI/input/plates/horse.mp4 --out /data/ComfyUI/input/plates/horse_hdr
  python tests/hdr_plate.py seam --plate /data/ComfyUI/input/plates/horse_hdr --export ~/paintaplate_gpu/hdr_dev/export.zip
"""
import argparse
import json
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


def untouched_difference(z, tmp: str, frames: list, results: list, mattes: list, every: int):
    """The largest difference from the plate where the delivered matte shows 0, on every `every`-th frame; None when the
    folder's frames are not the plate's size or channels."""
    worst = 0.0
    for i in range(0, len(frames), every):
        p = plateio.read_float(frames[i])
        r = plateio.read_float(z.extract(results[i], tmp))
        m = plateio.read_float(z.extract(mattes[i], tmp))[..., 0]
        if r.shape != p.shape or m.shape != p.shape[:2]:
            return None
        out = plateio.untouched(m)
        worst = max(worst, float(np.abs(r[out] - p[out]).max(initial=0.0)))
    return worst


def groups(plate: str, export: str, every: int = 30) -> dict:
    frames = plateio.find_sequence(plate)
    rows = []
    with zipfile.ZipFile(export) as z, tempfile.TemporaryDirectory() as tmp:
        names = z.namelist()
        mattes = _group(names, len(frames), True)
        folders = {}
        for n in sorted(names):
            if n.lower().endswith((".exr", ".png")):
                folders.setdefault(os.path.dirname(n), []).append(n)
        for folder, files in folders.items():
            exrs = [n for n in files if n.lower().endswith(".exr")]
            d = untouched_difference(z, tmp, frames, exrs, mattes, every) if len(exrs) == len(frames) else None
            rows.append((folder or ".", len(files), d))
    lines = [f"# The frame folders of `{export}`", "", f"The plate: {len(frames)} frames. The matte: `{os.path.dirname(mattes[0]) or '.'}`. "
             f"Differences on every {every}th frame from the first.", "",
             "| Folder | Files | Largest difference from the plate where the matte shows 0 |", "| --- | --- | --- |"]
    lines += [f"| {f} | {n} | {'' if d is None else f'{d:.4f}'} |" for f, n, d in rows]
    text = "\n".join(lines) + "\n"
    print(text)
    return {"rows": rows, "text": text}


DARK = 2.0 ** -10  # a level under this is read as this, so the noise of black does not swing in stops
LIMIT = {"stops": 0.01, "steps": 0.5}  # the swing from which a band shows
GOLD = (255, 190, 0)  # the sheet's mark over each band


def band_places(size: int, tile: int, overlap: int, work: int = 0) -> list:
    """The bands of a tiled decode along one side of a frame `size` px long, as (first, end) px: core's
    tiled_scale_multidim starts a tile every (tile - overlap) px of the decoded frame, `work` px long (0 for `size`), and
    blends two tiles over the `overlap` px from the later tile's edge. A frame brought to another size carries its bands."""
    work, step = work or size, tile - overlap
    return [(round(x * size / work), round((x + overlap) * size / work)) for x in range(step, work - overlap, step)]


def _frames(path: str) -> list:
    return plateio.find_sequence(path) if os.path.isdir(path) else [path]


def _swings(profile: np.ndarray, places: list) -> list:
    return [float(profile[a:b].max() - profile[a:b].min()) for a, b in places]


def _middles(places: list) -> list:
    """Windows as wide as a band at the middle of each tile's own part, between two bands, where it has room for one."""
    width = places[0][1] - places[0][0] if places else 0
    return [((b0 + a1) // 2 - width // 2, (b0 + a1) // 2 - width // 2 + width)
            for (_, b0), (a1, _) in zip(places, places[1:]) if a1 - b0 >= width]


def _sheet(path: str, test: np.ndarray, ref: np.ndarray, d: np.ndarray, places: dict, rows, steps: bool) -> tuple:
    """One PNG to look at: the tested frame, the reference frame and their difference, one above the other, from row
    rows[0] to rows[1], with a gold mark over each band. Scene-linear frames show 3 stops down through the sRGB curve,
    display frames as they are. In the difference, mid-grey is 0, and white or black is 0.1 stops (4 steps) or more."""
    from PIL import Image
    top, bottom = rows[0], min(rows[1], d.shape[0])

    def look(rgb):
        x = np.clip(rgb[top:bottom] * (1.0 if steps else 2.0 ** -3), 0.0, 1.0)
        if not steps:
            x = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)
        return (x * 255 + 0.5).astype(np.uint8)
    grey = (np.clip(0.5 + d[top:bottom] / (8.0 if steps else 0.2), 0.0, 1.0) * 255 + 0.5).astype(np.uint8)
    strips = [look(test), look(ref), np.repeat(grey[..., None], 3, -1)]
    for s in strips:
        for a, b in places["Columns"]:
            s[:6, a:b] = GOLD
        for a, b in places["Rows"]:
            if max(a, top) < min(b, bottom):
                s[max(a, top) - top:min(b, bottom) - top, :6] = GOLD
    gap = np.zeros((4, d.shape[1], 3), np.uint8)
    Image.fromarray(np.concatenate([strips[0], gap, strips[1], gap, strips[2]])).save(path)
    return top, bottom


def bands(ref: str, test: str, tile: int = 256, overlap: int = 64, work: str = "", steps: bool = False, every: int = 10,
          limit: float = 0.0, out: str = "", sheet: str = "", rows=(0, 432)) -> dict:
    """Where the tiles of a tiled decode show: the frames of `test` against those of `ref`, each a folder of frames or one
    frame. The column profile is the median over the frame of each column's difference, the row profile each row's. A
    band's swing is its profile's largest value minus its smallest across the band, read on every `every`th frame; the
    same swing at the middle of each tile's own part is the level a band is read against. `sheet` names a PNG of the
    first frame read (_sheet), from row rows[0] to rows[1]."""
    refs, tests = _frames(ref), _frames(test)
    count = min(len(refs), len(tests))
    picks = range(0, count, every)
    unit = "steps" if steps else "stops"
    limit = limit or LIMIT[unit]
    h, w = plateio.read_float(tests[0]).shape[:2]
    ww, wh = (int(v) for v in work.lower().split("x")) if work else (w, h)
    places = {"Columns": band_places(w, tile, overlap, ww), "Rows": band_places(h, tile, overlap, wh)}
    swing = {side: [] for side in places}
    calm = {side: [] for side in places}
    for i in picks:
        rr, tt = plateio.read_float(refs[i]), plateio.read_float(tests[i])
        r, t = rr.mean(-1), tt.mean(-1)
        if r.shape != t.shape:
            raise SystemExit(f"{refs[i]} is {r.shape[1]} x {r.shape[0]} and {tests[i]} is {t.shape[1]} x {t.shape[0]}")
        d = (t - r) * 255.0 if steps else np.log2(np.maximum(t, DARK) / np.maximum(r, DARK))
        for side, axis in (("Columns", 0), ("Rows", 1)):
            profile = np.median(d, axis=axis)
            swing[side].append(_swings(profile, places[side]))
            calm[side] += _swings(profile, _middles(places[side]))
        if sheet and i == picks[0]:
            shown = _sheet(sheet, tt, rr, d, places, rows, steps)
    rows = [(side, a, b, float(np.median(s)), float(np.max(s)))
            for side in places for (a, b), s in zip(places[side], np.array(swing[side]).reshape(len(picks), -1).T)]
    shows = [row for row in rows if row[3] > limit]
    top = max(rows, key=lambda row: row[3], default=None)
    controls = {side: float(np.median(v)) if v else None for side, v in calm.items()}
    what = "8-bit levels" if steps else "log2 of the ratio of the channels' mean"
    lines = [f"# The bands of `{test}` against `{ref}`", "",
             f"Tiles of {tile} px with {overlap} px of overlap on a decode of {ww} x {wh}: a tile every {tile - overlap} px. "
             f"Frames of {w} x {h}: {len(picks)} of {count} read, every {every}th from the first. The difference is in "
             f"{unit} ({what}); 0 is the reference's level. A band's swing is its profile's largest value minus its smallest "
             "across the band.", "",
             f"| Side | Band, px | Swing, median over the frames, {unit} | Largest swing, {unit} |", "| --- | --- | --- | --- |"]
    lines += [f"| {side} | {a} to {b} | {med:.3f} | {big:.3f} |" for side, a, b, med, big in rows]
    lines += ["", "The same swing at the middle of each tile's own part, the median: " + ", ".join(
        f"{side.lower()} {'no room' if v is None else f'{v:.3f} {unit}'}" for side, v in controls.items()) + ".", ""]
    if shows:
        n = {side: sum(1 for row in shows if row[0] == side) for side in places}
        lines.append(f"Bands over {limit:g} {unit}: {n['Columns']} of {len(places['Columns'])} column bands and {n['Rows']} of "
                     f"{len(places['Rows'])} row bands. The largest: {top[3]:.3f} {unit}, {top[0].lower()} {top[1]} to {top[2]}.")
    else:
        lines.append(f"No band over {limit:g} {unit}: the largest swing is {top[3] if top else 0.0:.3f} {unit}.")
    if sheet:
        lines += ["", f"Sheet `{os.path.basename(sheet)}`: frame {picks[0] + 1}, rows {shown[0]} to {shown[1]}. From the top: the "
                  "tested frame, the reference, their difference (mid-grey is 0, white or black "
                  f"{'4 steps' if steps else '0.1 stops'} or more); a gold mark over each band."]
    text = "\n".join(lines) + "\n"
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w") as f:
            f.write(text)
    print(text)
    return {"rows": rows, "shows": shows, "largest": top[3] if top else 0.0, "controls": controls, "text": text}


def _plate_info(path: str):
    """(width, height, frames) of a movie or of a folder of frames."""
    if os.path.isdir(path):
        frames = plateio.find_sequence(path)
        h, w = plateio.read_float(frames[0]).shape[:2]
        return w, h, len(frames)
    import av
    n = w = h = 0
    with av.open(path) as c:
        for f in c.decode(video=0):
            n, w, h = n + 1, f.width, f.height
    return w, h, n


def _comfy_pid():
    """The process of a ComfyUI started from main.py on this machine, or None."""
    for d in os.listdir("/proc"):
        if d.isdigit() and int(d) != os.getpid():
            try:
                with open(f"/proc/{d}/cmdline", "rb") as f:
                    args = f.read().split(b"\0")
            except OSError:
                continue
            if any(a.endswith(b"main.py") for a in args[:3]):
                return int(d)
    return None


def run_prompt(url: str, prompt: dict, pid=None, timeout: float = 7200.0) -> dict:
    """Post `prompt` to the ComfyUI at `url` and follow it: its seconds, the seconds of each node (from one « executing »
    message to the next), and the peaks read once a second: the GPU's memory in use and the RSS of process `pid`."""
    import asyncio
    import subprocess
    import threading
    import urllib.request
    import uuid
    import aiohttp
    cid, events, peaks, stop = uuid.uuid4().hex, [], {"vram": None, "ram": None}, threading.Event()

    def sample():
        while not stop.is_set():
            try:
                used = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                      capture_output=True, text=True, timeout=5).stdout.split()
                if used:
                    peaks["vram"] = max(peaks["vram"] or 0.0, float(used[0]) / 1024)
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
            if pid:
                try:
                    with open(f"/proc/{pid}/status") as f:
                        rss = next(int(line.split()[1]) for line in f if line.startswith("VmRSS:"))
                    peaks["ram"] = max(peaks["ram"] or 0.0, rss / 1048576)
                except (OSError, StopIteration, ValueError):
                    pass
            stop.wait(1.0)

    def history(job):
        with urllib.request.urlopen(f"{url}/history/{job}", timeout=30) as r:
            return json.loads(r.read()).get(job)

    async def follow():
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(url.replace("http", "ws", 1) + f"/ws?clientId={cid}", max_msg_size=0) as ws:
                req = urllib.request.Request(url + "/prompt", data=json.dumps({"prompt": prompt, "client_id": cid}).encode(),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    job = json.loads(r.read())["prompt_id"]
                t0 = time.time()
                while time.time() - t0 < timeout:
                    try:
                        msg = await ws.receive(timeout=1.0)
                    except asyncio.TimeoutError:
                        msg = None
                    if msg is not None and msg.type == aiohttp.WSMsgType.TEXT:
                        m = json.loads(msg.data)
                        d = m.get("data") or {}
                        if d.get("prompt_id") == job:
                            events.append((time.time(), m.get("type"), d.get("node")))
                            if m.get("type") in ("execution_success", "execution_error", "execution_interrupted"):
                                break
                            if m.get("type") == "executing" and d.get("node") is None:
                                break
                    elif msg is not None and msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    if msg is None:  # nothing said for a second: the history may hold the end
                        h = history(job)
                        if h and (h.get("outputs") or (h.get("status") or {}).get("completed") is not None):
                            break
                return job, t0, time.time()

    threading.Thread(target=sample, daemon=True).start()
    try:
        job, t0, t1 = asyncio.run(follow())
    finally:
        stop.set()
    return {"job": job, "seconds": t1 - t0, "spent": node_seconds(events, t0, t1), "peaks": peaks, "history": history(job) or {}}


BEFORE, AFTER = "before the first node", "after the last node"


def node_seconds(events: list, t0: float, t1: float) -> dict:
    """The seconds of each node of a job, from its « executing » message to the next « executing » one: the messages
    between them (a sampler's progress, an « executed ») belong to the node that runs. `events` holds (time, type, node)
    for the job's messages, `t0` is when the job was posted and `t1` when it ended. The seconds before the first node
    and after the last (its « executing » with no node) come under BEFORE and AFTER, so the values add up to t1 - t0."""
    starts = [(t, node) for t, kind, node in events if kind == "executing"]
    spent = {BEFORE: (starts[0][0] if starts else t1) - t0}
    for (t, node), (nxt, _) in zip(starts, starts[1:] + [(t1, None)]):
        key = AFTER if node is None else str(node)
        spent[key] = spent.get(key, 0.0) + nxt - t
    return spent


def node_rows(spent: dict, prompt: dict, top: int = 8) -> list:
    """(label, seconds) for a job's table: its `top` slowest nodes by class, the others in one row, then the seconds
    before the first node and after the last. The rows add up to the job's seconds."""
    nodes = sorted(((k, s) for k, s in spent.items() if k not in (BEFORE, AFTER)), key=lambda kv: -kv[1])
    rows = [(prompt.get(k, {}).get("class_type", k), s) for k, s in nodes[:top]]
    if nodes[top:]:
        rest = nodes[top:]
        rows.append((f"{len(rest)} other {'node' if len(rest) == 1 else 'nodes'}", sum(s for _, s in rest)))
    return rows + [(k.capitalize(), spent[k]) for k in (BEFORE, AFTER) if k in spent]


def decode_overlap(prompt: dict, overlap: int) -> int:
    """Set the overlap, in px, of every VAE Decode (Tiled) of a filled workflow; the count of nodes set."""
    nodes = [n for n in prompt.values() if n.get("class_type") == "VAEDecodeTiled"]
    for n in nodes:
        n["inputs"]["overlap"] = overlap
    return len(nodes)


def save_latent(prompt: dict, prefix: str) -> str:
    """Add core's Save Latent on the latent that the tiled decode reads, so tests/decode_cost.py can decode it again; the
    new node's id."""
    link = next(n["inputs"]["samples"] for n in prompt.values() if n.get("class_type") == "VAEDecodeTiled")
    key = str(max(int(k) for k in prompt) + 1)
    prompt[key] = {"class_type": "SaveLatent", "inputs": {"samples": link, "filename_prefix": prefix}}
    return key


def finish(url: str, comfy: str, plate: str, out: str, label: str = "finish", width: int = 0, height: int = 0,
           tile=None, guide_tiled=None, color_space: str = "@model", overlap=None, latent: bool = False) -> dict:
    """SDR to HDR on a plate with no edit, as the page's Finish runs it, timed node by node: a report in `out`."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import build_workflows
    full = os.path.join(comfy, "input", plate)
    if not os.path.exists(full):
        full = next(os.path.join(d, f) for d, _, fs in os.walk(comfy) for f in fs if f == os.path.basename(plate))
    w, h, n = _plate_info(full)
    up = lambda v: -(-v // 32) * 32  # noqa: E731
    ww, wh, count = width or up(w), height or up(h), min(n, 121)
    values = {"path": plate, "color_space": color_space, "max_frames": count, "width": ww, "height": wh, "plate_width": w,
              "plate_height": h, "prefix": f"{label}/hdr/f", "video_prefix": f"{label}/hdr_movie"}
    values.update({k: v for k, v in (("tile", tile), ("guide_tiled", guide_tiled)) if v is not None})
    prompt = build_workflows.fill("hdr", values)
    if overlap is not None:
        decode_overlap(prompt, overlap)
    if latent:
        save_latent(prompt, f"{label}/latent")
    ov = next((n["inputs"]["overlap"] for n in prompt.values() if n.get("class_type") == "VAEDecodeTiled"), None)
    r = run_prompt(url, prompt, pid=_comfy_pid())
    exrs = sorted(glob.glob(os.path.join(comfy, "output", label, "hdr", "*.exr")))
    size = plateio.read_float(exrs[0]).shape[:2] if exrs else None
    status = (r["history"].get("status") or {}).get("status_str", "no status")
    gb = lambda v: "not read" if v is None else f"{v:.1f} GB"  # noqa: E731
    by = sorted(((k, s) for k, s in r["spent"].items() if k not in (BEFORE, AFTER)), key=lambda kv: -kv[1])
    lines = [f"# SDR to HDR on a plate with no edit: `{plate}`", "", "| | |", "| --- | --- |",
             f"| ComfyUI | {url}, job {r['job'][:8]}: {status} |",
             f"| Plate | {w} x {h}, {count} frames, working size {ww} x {wh} |",
             f"| Slots | tile {values.get('tile', 'default')}, the decode's overlap {ov} px, guide_tiled {values.get('guide_tiled', 'default')}, colour space {color_space} |",
             f"| Seconds | {r['seconds']:.1f} |", f"| Peak VRAM | {gb(r['peaks']['vram'])}, the GPU's memory in use |",
             f"| Peak RAM | {gb(r['peaks']['ram'])}, ComfyUI's process |",
             f"| HDR frames | {len(exrs)} EXR frames" + (f" at {size[1]} x {size[0]}" if size else "") + " |", "",
             "GB means 2^30 bytes.", "", "| Node | Seconds |", "| --- | --- |"]
    lines += [f"| {label} | {s:.1f} |" for label, s in node_rows(r["spent"], prompt)]
    text = "\n".join(lines) + "\n"
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"{label}.md"), "w") as f:
        f.write(text)
    print(text)
    return {"seconds": r["seconds"], "frames": len(exrs), "size": size, "status": status, "by_node": by, "peaks": r["peaks"]}


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
    gr = sub.add_parser("groups", help="each frame folder of the zip, and its untouched pixels against the plate")
    gr.add_argument("--plate", required=True)
    gr.add_argument("--export", required=True, help="the export.zip that tests/ui_live.py downloads")
    gr.add_argument("--every", type=int, default=30)
    b = sub.add_parser("bands", help="where a tiled decode's tiles show: its frames against the same latent decoded whole")
    b.add_argument("--ref", required=True, help="the frames decoded whole: a folder of frames or one frame")
    b.add_argument("--test", required=True, help="the frames decoded in tiles: a folder of frames or one frame")
    b.add_argument("--tile", type=int, default=256, help="the tiled decode's tile in px")
    b.add_argument("--overlap", type=int, default=64, help="the tiled decode's overlap in px")
    b.add_argument("--work", default="", help="the decode's size, such as 1920x1088, when the frames were brought to another size")
    b.add_argument("--steps", action="store_true", help="the difference in 8-bit steps, for display frames; in stops otherwise")
    b.add_argument("--every", type=int, default=10, help="read every this many frames, from the first")
    b.add_argument("--limit", type=float, help="the swing from which a band shows: 0.01 stops, or 0.5 steps with --steps")
    b.add_argument("--out", default="", help="a Markdown file for the report")
    b.add_argument("--sheet", default="", help="a PNG of the first frame read: the tested frame, the reference and their difference")
    b.add_argument("--rows", type=int, nargs=2, default=(0, 432), help="the sheet's first row and the row after its last")
    fi = sub.add_parser("finish", help="SDR to HDR on a plate with no edit, timed node by node, on a running ComfyUI")
    fi.add_argument("--url", default="http://127.0.0.1:8188")
    fi.add_argument("--comfy", required=True, help="ComfyUI's folder: the plate under its input folder, the frames under its output folder")
    fi.add_argument("--plate", required=True, help="the plate as Load Plate takes it, such as plates/horse.mp4")
    fi.add_argument("--out", required=True, help="the folder of the report")
    fi.add_argument("--label", default="finish", help="the report's name and the frames' folder under ComfyUI's output folder")
    fi.add_argument("--width", type=int, default=0, help="the working width: 0 is the plate's, up to a multiple of 32")
    fi.add_argument("--height", type=int, default=0, help="the working height: 0 is the plate's, up to a multiple of 32")
    fi.add_argument("--tile", type=int, help="the decode's tile in px, as the page's memory profile sends it")
    fi.add_argument("--overlap", type=int, help="the decode's overlap in px; VAE Decode (Tiled) takes at most a quarter of the tile")
    fi.add_argument("--latent", action="store_true", help="also save the latent the decode reads, under the frames' folder")
    fi.add_argument("--guide-tiled", type=int, choices=(0, 1), help="1 encodes the guide in tiles, as the page's small profile does")
    fi.add_argument("--color-space", default="@model", help="the plate's file colour space in the OCIO config")
    a = ap.parse_args()
    if a.what == "make":
        make(a.source, a.out, a.peak, a.frames)
    elif a.what == "seam":
        seam(a.plate, a.export, a.ring, a.every)
    elif a.what == "groups":
        groups(a.plate, a.export, a.every)
    elif a.what == "bands":
        bands(a.ref, a.test, a.tile, a.overlap, a.work, a.steps, a.every, a.limit or 0.0, os.path.expanduser(a.out) if a.out else "",
              os.path.expanduser(a.sheet) if a.sheet else "", a.rows)
    else:
        finish(a.url, a.comfy, a.plate, os.path.expanduser(a.out), a.label, a.width, a.height, a.tile,
               None if a.guide_tiled is None else bool(a.guide_tiled), a.color_space, a.overlap, a.latent)
