"""One GPU test for a pod and for a laptop: the real page over a list of cases, and one report.

    python tests/gpu_matrix.py --url http://127.0.0.1:8188 --comfy <ComfyUI folder> --out <folder> --cases quick

Each case runs tests/ui_live.py on a running ComfyUI (the real page, in Google Chrome). This script then reads what the
case left behind and writes <out>/report.md: the machine, then per case the time of each step (the page's log times
every step), each job with its seconds, its peak VRAM and RAM, the nodes ComfyUI took from its cache and the previews
the page received, out-of-memory retries, the memory profile, the paint matte's area on every frame against the first
frame's, pass or fail, the page's verdict on a Clean edit (gone or left), then the log of each failure. The report is written again after every case, so a run that is
stopped still leaves one.

Memory is read once a second. VRAM comes from ComfyUI's /system_stats. RAM is what ComfyUI's own process holds (VmRSS in
/proc/<pid>/status, as tests/open_probe.py reads it), and of it the part that no file backs (RssAnon and RssShmem): a
memory cap can take back the pages of a model file, never that part. A job's peak is the highest reading between its
start and its end in ComfyUI's /history.

quick: on plates/horse.mp4 (python get_plates.py) a cow painted behind the fence, one erase, one light, then a fluid shot
at 1280 x 704 x 121. all adds a 3840 x 2160 plate at 50 fps, made here from horse.mp4 (paint, erase, light), a fluid
shot at 1920 x 1088 at 50 fps with one edit on it, then the same 3840 x 2160 plate at 25 fps. --cases also takes case
names, with commas. The strokes and the seed of each case are in gpu_matrix.json beside this file: a case paints the
same strokes from the same seed at every run, so a wrong picture comes back at the next run. --seeds 7,8,9 runs each
case once per seed, in place of its own. ui_live.py opens the page with ?index=0: the page leaves its job index alone,
so every job runs and every time is a measured one. --memory small,
medium or large asks the page for that memory profile (logic.memoryProfile) in place of the one the card gives: the same
case under two profiles shows what a profile costs.

It needs Playwright with Google Chrome: Playwright's own Chromium cannot play H.264. Run it on the machine that runs
ComfyUI, with a Python that has Pillow and numpy (ComfyUI's own has both): it reads ComfyUI's process, and the mattes and
the live previews in ComfyUI's output and temp folders.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
try:  # ComfyUI's process, read as the plate's probe reads it; where it cannot be read, the system's RAM in use serves
    from open_probe import local_pid, status_bytes  # noqa: E402
except ImportError:
    local_pid = status_bytes = None

QUICK = ("horse_cow", "horse_erase", "horse_light", "fluid_720")
ALL = QUICK + ("uhd_cow", "uhd_erase", "uhd_light", "fluid_1080_edit", "uhd25_cow", "uhd25_erase", "uhd25_light")
UHD = {"horse_3840x2160_50fps.mp4": 50, "horse_3840x2160_25fps.mp4": 25}  # « 4K at 50 fps », and at 25: every tool runs on a 3840 x 2160 plate
UHD_SIZE, UHD_FRAMES = (3840, 2160), 121
STEP = re.compile(r"Render v(\d+): (.+?) took ([\d.]+) s")  # the page's log: one line per render step
# and one line per finished job: its id, its seconds, its nodes, those ComfyUI took from its cache (a model loader among
# them is a model not loaded again) and the previews the page received. A line starts with its time, with no space after it
JOB = re.compile(r"([a-z]+) ([0-9a-f?]{1,8}): done in ([\d.]+) s \((\d+) nodes?(?:, (\d+) from ComfyUI's cache)?(?:, (\d+) previews?)?")
ENDED = re.compile(r"([a-z]+ [0-9a-f?]{1,8}: (?:failed|stopped) after [^\n]*)")  # a job that did not finish says so in one line
RETRY = "The GPU ran out of memory: freeing ComfyUI's memory, then trying once more"  # the page's one line for a retry (web/comfy.mjs)
GB = 2 ** 30


def stop(sentence):
    print(sentence)
    sys.exit(2)


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Paint a plate gpu_matrix)"})  # Runpod's proxy refuses urllib's own
    with urllib.request.urlopen(request, timeout=10) as r:
        return json.load(r)


def answers(url):
    """Whether ComfyUI still answers."""
    try:
        get(url + "/system_stats")
        return True
    except (OSError, ValueError):
        return False


def free(url):
    """ComfyUI unloads its models and drops its cached results, as the page's own free asks. It does so at its next
    idle moment: 5 s leave it the time."""
    body = json.dumps({"unload_models": True, "free_memory": True}).encode()
    request = urllib.request.Request(url + "/free", data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Paint a plate gpu_matrix)"})
    urllib.request.urlopen(request, timeout=30).close()
    time.sleep(5)


class Memory(threading.Thread):
    """VRAM and RAM in use while a case runs, read once a second (the top of this file says from where). `samples` keeps
    every reading with its time: (time, VRAM, RAM, RAM that no file backs). In a container, `container` is its own count
    (/sys/fs/cgroup/memory.current), which holds the page cache too."""
    CGROUP = "/sys/fs/cgroup/memory.current"

    def __init__(self, url):
        super().__init__(daemon=True)
        self.url, self.on, self.samples, self.container = url, True, [], 0
        try:
            self.pid = local_pid(url) if local_pid else None
        except Exception:
            self.pid = None  # no /proc, or ComfyUI runs on another machine

    def held(self, *fields):
        try:
            return sum(status_bytes(self.pid, field) or 0 for field in fields)
        except Exception:
            return 0

    def run(self):
        vram = 0
        while self.on:
            ram = own = 0
            try:
                stats = get(self.url + "/system_stats")
                gpu = (stats.get("devices") or [{}])[0]
                vram = gpu.get("vram_total", 0) - gpu.get("vram_free", 0)
                ram = own = stats["system"].get("ram_total", 0) - stats["system"].get("ram_free", 0)
            except (OSError, ValueError, KeyError):
                pass  # ComfyUI is busy or restarting: the last VRAM reading holds, and the next second asks again
            if self.pid:
                ram, own = self.held("VmRSS"), self.held("RssAnon", "RssShmem")
            self.samples.append((time.time(), vram, ram, own))
            try:
                with open(self.CGROUP) as f:
                    self.container = max(self.container, int(f.read()))
            except (OSError, ValueError):
                pass  # not a container
            time.sleep(1)

    def peak(self, t0=0.0, t1=float("inf")):
        """The most VRAM, RAM and RAM that no file backs between two times. A job shorter than a second may hold no
        reading: then the reading nearest to its end."""
        inside = [s for s in self.samples if t0 <= s[0] <= t1] or sorted(self.samples, key=lambda s: abs(s[0] - t1))[:1]
        return [max(s[k] for s in inside) for k in (1, 2, 3)] if inside else [0, 0, 0]


def job_spans(history):
    """When ComfyUI ran each job of its /history: {the id's first 8 characters: (start, end)}, in seconds."""
    spans = {}
    for prompt_id, entry in history.items():
        stamps = {kind: data.get("timestamp") for kind, data in (entry.get("status") or {}).get("messages", []) if isinstance(data, dict)}
        end = stamps.get("execution_success") or stamps.get("execution_error") or stamps.get("execution_interrupted")
        if stamps.get("execution_start") and end:
            spans[prompt_id[:8]] = (stamps["execution_start"] / 1000, end / 1000)
    return spans


FAILED_JOB = re.compile(r"(\w+) ([0-9a-f]{8}): failed after")  # a job line of the page that ComfyUI did not finish


def workflow(name):
    """The pack's own API graph of a job (web/workflows/<name>.json), with the node ids the page posts: what names the nodes
    of a job that ComfyUI's /history no longer holds, after ComfyUI stopped. {} when there is none."""
    try:
        with open(os.path.join(REPO, "web", "workflows", f"{name}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return {}


def running_at_stop(events, graphs, names=None):
    """The node each job was running when its messages stopped with no end (ComfyUI stopped): {id[:8]: node class}."""
    last = {}
    for _, pid, node in events:
        last[pid] = node
    return {(pid or "")[:8]: ((graphs.get(pid) or workflow((names or {}).get((pid or "")[:8]))).get(str(node)) or {}).get("class_type", f"node {node}")
            for pid, node in last.items() if node is not None}


def node_times(events, graphs, names=None):
    """Where each job's time went: {the id's first 8 characters: [(node class, seconds), ...], longest first}. Each «
    executing » message starts a node and ends the one before; the one with no node ends the job. events: [[seconds,
    prompt id, node id or None]] (ui_live.py's nodes.json); graphs: {prompt id: its API graph, from ComfyUI's /history};
    names: {id[:8]: job name}, for a job that /history no longer holds: its nodes are named from the pack's workflow."""
    runs, out = {}, {}
    for t, pid, node in events:
        runs.setdefault(pid, []).append((t, node))
    for pid, seq in runs.items():
        graph, spent = graphs.get(pid) or workflow((names or {}).get((pid or "")[:8])), {}
        for (t, node), (later, _) in zip(seq, seq[1:]):
            if node is not None:
                name = (graph.get(str(node)) or {}).get("class_type", f"node {node}")
                spent[name] = round(spent.get(name, 0.0) + later - t, 1)
        out[(pid or "")[:8]] = sorted(spent.items(), key=lambda x: -x[1])
    return out


def render_hdr(steps):
    """Whether a render ran SDR to HDR (« v1 SDR to HDR »): only a render's composite writes HDR Match's line. A fluid shot's
    own pass (« fluid v1 SDR to HDR ») has no plate to match: fluid_720 of 13 Nov was told to look for a line that never was."""
    return any(re.match(r"v\d+ SDR to HDR\b", label) for label, _ in steps)


def comfy_lines(url, since, mark="PaintAPlate HDR Match:"):
    """ComfyUI's own log lines since `since` (its local time, ISO) that hold `mark`, from its /internal/logs/raw. It keeps the
    last few hundred lines only: [] when they are gone, or when this ComfyUI has no such route."""
    try:
        entries = get(url + "/internal/logs/raw").get("entries", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [e["m"].strip() for e in entries if e.get("t", "") >= since and mark in e.get("m", "")]


def browser_ready(channel):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        stop("Playwright is missing: run `python -m pip install playwright`, then `python -m playwright install chrome`.")
    try:
        with sync_playwright() as p:
            p.chromium.launch(channel=channel or None).close()
    except Exception:
        stop("Google Chrome is missing: run `python -m playwright install chrome`. Playwright's own Chromium cannot play H.264, "
             "so the page's player never runs in it.")


def make_uhd(source, target, fps):
    """A 3840 x 2160 plate at `fps`: horse.mp4's first 121 frames, enlarged with Lanczos by the pack's own movie writer."""
    try:
        import av
    except ImportError:
        stop("PyAV is missing: run this script with ComfyUI's own Python, or `pip install av`.")
    sys.path.insert(0, REPO)
    import plateio
    with av.open(source) as src:
        frames = [f.to_ndarray(format="rgb24") for _, f in zip(range(UHD_FRAMES), src.decode(video=0))]
    plateio.write_movie(lambda i: frames[i], len(frames), target, fps, crf=14, preset="medium", size=UHD_SIZE)


def load_cases():
    """The cases of gpu_matrix.json, by name. A case with « like » takes another case's strokes, the brush scaled to its own
    plate, and that case's seed unless it holds one."""
    with open(os.path.join(HERE, "gpu_matrix.json"), encoding="utf-8") as f:
        cases = {name: case for name, case in json.load(f).items() if isinstance(case, dict)}  # « note » is a sentence
    for case in cases.values():
        if "like" in case:
            source = cases[case["like"]]
            case["strokes"] = [[*s[:3], round(s[3] * case.get("scale", 1)), *s[4:]] for s in source["strokes"]]
            case.setdefault("seed", source.get("seed"))
    return cases


def seeds_asked(text):
    """--seeds 7,8,9 as numbers. Without it, [None]: each case runs once, from its own seed."""
    if not text:
        return [None]
    seeds = [int(s) if s.strip().isdigit() else -1 for s in text.split(",")]
    if any(not 0 <= s < 2 ** 31 for s in seeds):
        stop("--seeds takes whole numbers from 0 to 2147483647, with commas: the seeds the page accepts in ?seed=.")
    return seeds


def command(a, case, folder):
    """ui_live.py's command for one case: its plate or its fluid shot, its strokes as written, its seed."""
    cmd = [sys.executable, os.path.join(HERE, "ui_live.py"), "--url", a.url, "--comfy", a.comfy, "--out", folder,
           "--channel", a.channel, "--timeout", str(a.timeout), "--think", "2", *(["--memory", a.memory] if a.memory else []), *(["--graph"] if a.graph else []),
           *(["--hdr"] if getattr(a, "hdr", False) or case.get("hdr") else [])]
    cmd += ["--fluid", json.dumps(case["fluid"])] if "fluid" in case else ["--path", case["path"]]
    if case.get("strokes"):
        cmd += ["--strokes", json.dumps(case["strokes"])]
    if case.get("seed") is not None:
        cmd += ["--seed", str(case["seed"])]
    return cmd


def seed_note(asked, named):
    """A case's line on its seed: the one it asked the page for, and the seeds that the page's log names for its edits, its
    fluid shot and its render."""
    said = f"Seed asked for: {'none, the page draws one' if asked is None else asked}. In the page's log: {', '.join(named) or 'none'}."
    return said if asked is None or named == [str(asked)] else said + " The page did not start from the seed asked for: its version may not read ?seed= yet."


def matte_areas(comfy, since):
    """The paint matte this case wrote (the full-size one if there is one): its folder, and its area on every frame."""
    import numpy as np
    from PIL import Image
    best = None
    for folder in glob.glob(os.path.join(comfy, "output", "paintaplate", "**", "matte_b*"), recursive=True):
        frames = sorted(glob.glob(os.path.join(folder, "*.png")))
        if frames and os.path.getmtime(frames[-1]) >= since:
            found = ((folder.endswith("_full"), os.path.getmtime(frames[-1])), folder, frames)
            best = max(best, found) if best else found
    if not best:
        return None
    return best[1], [float((np.asarray(Image.open(f).convert("L")) > 127).mean()) for f in best[2]]


def log_steps(text):
    """The steps the page times, in its log's order: each render step (« Render vN: … took … s »); for a fluid shot its LTX
    pass (the fluid job after « Fluid vN: »), each step timed (« Fluid vN: SDR to HDR took … s ») and the whole shot."""
    steps, fluid = [], "?"
    for line in text.splitlines():
        if m := STEP.search(line):
            steps.append((f"v{m.group(1)} {m.group(2)}", float(m.group(3))))
        elif m := re.search(r"Fluid v(\d+): (.+?) took ([\d.]+) s", line):
            steps.append((f"fluid v{m.group(1)} {m.group(2)}", float(m.group(3))))
        elif m := re.search(r"Fluid v(\d+): done in ([\d.]+) s", line):
            steps.append((f"fluid v{m.group(1)} in all", float(m.group(2))))
        elif m := re.search(r"Fluid v(\d+):", line):
            fluid = m.group(1)
        elif m := re.search(r"(?<![a-z])fluid [0-9a-f?]{1,8}: done in ([\d.]+) s", line):
            steps.append((f"fluid v{fluid} LTX pass", float(m.group(1))))
    return steps


def carried(r, fresh, gb):
    """Without --fresh, ComfyUI holds what ran before a case: its first job's peak RAM can be that, not the case's own."""
    j = next(iter(r["jobs"]), None)
    if fresh or not j or j.get("run") is None:
        return []
    return [f"- ComfyUI was not freed before this case (no --fresh): the first job's peak RAM, {gb(j['ram'])} for {j['name']} {j['id']}, "
            "can be what the case before left. Run with --fresh for this case's own."]


def estimates_off(steps, announced):
    """The steps that took more than 25% over or under what the page announced before they started (logic.stepGuess)."""
    return [f"{label}: about {announced[label]} s, took {s:.1f} s" for label, s in steps
            if announced.get(label) and abs(s - announced[label]) > 0.25 * s]


def read_log(text):
    """What a case's page log says: the render steps and the jobs with their seconds, and the counts the report shows."""
    profile = re.search(r"Memory profile (\w+): ([^\n]*)", text)
    jobs = [{"name": name, "id": job, "seconds": float(s), "nodes": int(n), "cached": int(k or 0), "previews": int(p or 0)}
            for name, job, s, n, k, p in JOB.findall(text)]
    return {
        "steps": log_steps(text),
        "jobs": jobs,
        "ended": ENDED.findall(text),
        "indexed": text.count("taken from the job index"),
        "oom": text.count(RETRY),
        "previews": sum(j["previews"] for j in jobs),
        "live_off": re.findall(r"Live preview is off: ([^\n]*)", text),
        "profile": f"{profile.group(1)} ({profile.group(2)})" if profile else "not in the log's last 400 lines",
        "mattes": re.findall(r"([A-Z][a-z]+ matte(?: \([^)\n]*\))?: tracked on [^\n]*(?:\n  [^\n]*)*)", text),  # any word before « matte »; the headline and its detail lines (mathops.follow_summary)
        "seeds": sorted(set(re.findall(r"\bseed (\d+)", text)), key=int),
        "announced": {f"v{v} {label}": int(s) for v, label, s in re.findall(r"Render v(\d+): (.+?) \(about (\d+) s\)", text)},
        "figures": re.findall(r"(Edit \d+: [^\n]*?\(\d+% of it changed[^)\n]*\))", text),  # an erase: how much of the object changed, gone or held back (logic.leftLines)
    }


# ---------- The pictures: one sheet per case (wave 6, R10) ----------
# On 12 Nov horse_erase passed with the barn still in its result, and nothing in the report showed it. The sheet puts the
# plate and the export side by side, cut around each edit's box, on four frames: the first, at a third, at two thirds and
# the last. With one edit the box follows the export's matte from frame to frame; a relight shows the whole frame. For an
# erase the sheet writes the page's own verdict (wave 7, R15): logic.eraseCheck, run with Node through tests/erase_probe.py,
# on the export's first frame against the plate's, inside the mask the page sent Klein, at the page's quick-pass size.
SHEET_CELL = (360, 240)  # the largest picture of one frame on the sheet, in pixels
IMAGES = (".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff")
MOVIES = (".mp4", ".mov", ".webm", ".mkv")
TOOL_NAMES = {"paint": "Paint", "erase": "Clean", "light": "Light"}


def frames_source(path):
    """A movie's path as it is, or the image files of a folder in order (an image sequence)."""
    return sorted(f for f in glob.glob(os.path.join(path, "*")) if f.lower().endswith(IMAGES)) if os.path.isdir(path) else path


def image_rgb(path):
    """One image file as 8-bit RGB. An EXR's values are clipped at 1.0 under a plain 2.2 gamma: enough to see what is there."""
    import numpy as np
    from PIL import Image
    if path.lower().endswith(".exr"):
        if REPO not in sys.path:
            sys.path.insert(0, REPO)
        import plateio
        return (np.clip(plateio.read_float(path)[..., :3], 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def media_count(src):
    """How many frames a movie or a list of image files holds."""
    if isinstance(src, list):
        return len(src)
    import av
    with av.open(src) as c:
        stream = c.streams.video[0]
        return stream.frames or sum(1 for p in c.demux(stream) if p.size)


def media_frames(src, want):
    """{index: RGB uint8 array} for the frames `want` of a movie or of a list of image files."""
    if isinstance(src, list):
        return {i: image_rgb(src[min(i, len(src) - 1)]) for i in want}
    import av
    out = {}
    with av.open(src) as c:
        for i, frame in enumerate(c.decode(video=0)):
            if i in want:
                out[i] = frame.to_ndarray(format="rgb24")
            if i >= max(want):
                break
    return out


def edit_box(stroke, width, height):
    """An edit's box on the first frame, in pixels: its stroke's points, and half its brush around them."""
    xs, ys, r = [p[0] * width for p in stroke[2]], [p[1] * height for p in stroke[2]], (stroke[3] if len(stroke) > 3 else 64) / 2
    return (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)


def matte_box(path, width, height):
    """The box around a matte frame's white, at the frame's size; None when the frame holds none."""
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        m = np.asarray(im.convert("L")) > 127
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    sx, sy = width / m.shape[1], height / m.shape[0]
    return (xs.min() * sx, ys.min() * sy, (xs.max() + 1) * sx, (ys.max() + 1) * sy)


def framed(box, width, height, least=160):
    """The box with as much again around it, at least `least` pixels a side, inside the frame."""
    (x0, y0, x1, y1), cx, cy = box, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    w, h = min(max((x1 - x0) * 2, least), width), min(max((y1 - y0) * 2, least), height)
    left, top = min(max(0, cx - w / 2), width - w), min(max(0, cy - h / 2), height - h)
    return (int(left), int(top), int(left + w), int(top + h))


def page_mask(comfy, since):
    """The mask the page sent Klein for an erase: the newest *_mask_full*.png in ComfyUI's input folder written since
    `since` (seconds since the epoch), or None."""
    found = [f for f in glob.glob(os.path.join(comfy, "input", "**", "*_mask_full*.png"), recursive=True) if os.path.getmtime(f) >= since]
    return max(found, key=os.path.getmtime) if found else None


def quick_size(log):
    """The page's quick-pass size, from its line « Working sizes: ... quick passes at 768 x 432 ... »: the size the page
    judges an erase at (app.mjs, `p.prev`). The same line's « preview at 640 x 352 » is the shot's preview, another size.
    None when the log has no such line."""
    found = re.findall(r"quick passes at (\d+) x (\d+)", log)
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def erase_verdict(after, before, mask, size):
    """The page's verdict on an erase, logic.eraseCheck run with Node: `after` the export's first frame and `before` the
    plate's (RGB, 8 bits), `mask` the file the page sent Klein, all three drawn at `size` as the page's canvases draw them
    (tests/erase_probe.py: one bridge, one resize). {"left": True, False or None, "changed", "edges", "text"}."""
    def none(why):
        return {"left": None, "changed": None, "edges": None, "text": f"Clean, frame 1: no verdict. {why}."}
    if not mask:
        return none("No mask from the page in ComfyUI's input folder since the case started")
    if not size:
        return none("No quick-pass size in the page's log")
    import numpy as np
    from PIL import Image
    import erase_probe as probe
    with Image.open(mask) as im:
        held = probe.mask_at(np.asarray(im.convert("L")) > 127, size)
    if not held.any():
        return none(f"The mask is empty at {size[0]} x {size[1]}")
    got = probe.page(("eraseCheck", probe.raw(probe.rgba(probe.resized(after, size))), probe.raw(probe.rgba(probe.resized(before, size))),
                      probe.raw(probe.rgba(probe.white(held))), size[0], size[1]))[0]
    figures = [f"{round(100 * got['changed'])}% of the object changed" if got.get("changed") is not None else "",
               f"edges held at {got['edges']:.2f}" if got.get("edges") is not None else ""]
    detail = "; ".join(f for f in figures if f)
    return {**got, "text": f"Clean, frame 1: {'left' if got['left'] else 'gone'}" + (f" ({detail})." if detail else ".")}


def name_asked(marks, log, jobs):
    """A case that expects the page to ask for an erase's object by name (gpu_matrix.json: « expect »: « name asked »,
    logic.asksName) passes when the page asked and neither Klein nor LTX ran. (passed, why)."""
    asked = any(m.startswith("name asked") for m in marks)
    ran = [what for what, found in (("a Klein pass", re.search(r"Klein (quick|full-size) pass", log)),
                                    ("a shot", any(j["name"] == "shot" for j in jobs))) if found]
    return asked and not ran, "" if asked and not ran else "the page did not ask for the name" if not asked else " and ".join(ran) + " ran"


def sheet(case, folder, plate, others=(), mask=None, judge_at=None):
    """The case's sheet, sheet.png in its folder: for each edit, the plate and the export cut around its box, on the first
    frame, at a third, at two thirds and on the last. `others`: more (title, export.zip) columns, such as another run of
    the same strokes. `mask` and `judge_at`: the mask the page sent Klein (page_mask) and the page's quick-pass size
    (quick_size), for the verdict on a Clean edit (erase_verdict). {"path", "frames" (from 1), "cells": [(row, column, x0,
    y0, x1, y1)], "verdict": that verdict or None}, or None with no export or plate."""
    from PIL import Image, ImageDraw, ImageFont
    strokes, export = case.get("strokes") or [], os.path.join(folder, "export.zip")
    if not strokes or not os.path.exists(export) or not plate or not os.path.exists(plate):
        return None
    work, columns, mattes = os.path.join(folder, "sheet_files"), [("plate", frames_source(plate))], []
    try:
        for title, path in (("export", export), *others):
            into = os.path.join(work, title.replace(" ", "_"))
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.startswith(("export/", "matte/")) and not n.endswith("/")]
                z.extractall(into, names)
            movies = [n for n in names if n.startswith("export/") and n.lower().endswith(MOVIES)]
            columns.append((title, os.path.join(into, movies[0]) if movies else
                            [os.path.join(into, n) for n in sorted(names) if n.startswith("export/") and n.lower().endswith(IMAGES)]))
            mattes = mattes or sorted(glob.glob(os.path.join(into, "matte", "*.png")))
        count = media_count(columns[1][1])
        rows = sorted({0, count // 3, 2 * count // 3, count - 1})
        pictures = [media_frames(src, rows) for _, src in columns]
        height, width = pictures[1][rows[0]].shape[:2]
        erases = [s for s in strokes if s[0] == "erase"]
        verdict = None if not erases else erase_verdict(pictures[1][rows[0]], pictures[0][rows[0]], mask, judge_at) if len(erases) == 1 else \
            {"left": None, "changed": None, "edges": None, "text": f"Clean, frame 1: no verdict. {len(erases)} Clean edits share the frame."}
        edits = []
        for s in strokes:
            if s[0] == "light" or not mattes and s[0] != "erase" and s[0] != "paint":
                edits.append((s, [(0, 0, width, height)] * len(rows)))
                continue
            last, boxes = edit_box(s, width, height), []
            for i in rows:
                found = matte_box(mattes[min(i, len(mattes) - 1)], width, height) if mattes and len(strokes) == 1 else None
                last = found or last
                boxes.append(framed(last, width, height))
            edits.append((s, boxes))
        (cw, ch), gap, head, left = SHEET_CELL, 8, 24, 76
        try:
            font = ImageFont.load_default(size=15)
        except TypeError:
            font = ImageFont.load_default()
        span = len(columns) * (cw + gap)
        out = Image.new("RGB", (left + len(edits) * span, 2 * head + len(rows) * (ch + gap) + head), (28, 28, 28))
        draw, cells = ImageDraw.Draw(out), []
        for e, (s, boxes) in enumerate(edits):
            x = left + e * span
            draw.text((x, 4), f"Edit {e + 1}: {TOOL_NAMES.get(s[0], s[0])} " + (f'"{s[1][:40]}"' if s[1] else "(no words)"), fill="white", font=font)
            for c, (title, _) in enumerate(columns):
                draw.text((x + c * (cw + gap), head + 2), title, fill=(200, 200, 200), font=font)
            for r, i in enumerate(rows):
                for c in range(len(columns)):
                    crop = Image.fromarray(pictures[c].get(i, pictures[c][max(k for k in pictures[c] if k <= i)])).crop(boxes[r])
                    crop.thumbnail((cw, ch))
                    at = (x + c * (cw + gap), 2 * head + r * (ch + gap))
                    out.paste(crop, at)
                    cells.append((r, c, at[0], at[1], at[0] + crop.width, at[1] + crop.height))
            if s[0] == "erase" and verdict:
                draw.text((x, out.height - head + 4), verdict["text"], fill=(120, 220, 120) if verdict["left"] is False else (255, 200, 80), font=font)
        for r, i in enumerate(rows):
            draw.text((6, 2 * head + r * (ch + gap) + 4), f"frame {i + 1}", fill="white", font=font)
        path = os.path.join(folder, "sheet.png")
        out.save(path)
        return {"path": path, "frames": [i + 1 for i in rows], "cells": cells, "verdict": verdict}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_case(a, name, case, folder):
    memory, t0 = Memory(a.url), time.time()
    memory.start()
    print(f"--- {name}", flush=True)
    subprocess.run(command(a, case, folder))
    memory.on = False
    memory.join(3)
    vram, ram, own = memory.peak()
    result = {"name": name, "strokes": case.get("strokes") or [], "hdr_match": comfy_lines(a.url, time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0))), "seconds": time.time() - t0, "vram": vram, "ram": ram, "own": own, "container": memory.container, "folder": folder, "seed": case.get("seed")}
    log_file, marks_file = os.path.join(folder, "page_log.txt"), os.path.join(folder, "timings.json")
    result["log"] = open(log_file, encoding="utf-8").read() if os.path.exists(log_file) else ""
    marks = json.load(open(marks_file)).get("marks", []) if os.path.exists(marks_file) else []
    result["marks"] = [what for _, what in marks]
    result.update(read_log(result["log"]))
    try:
        history = get(a.url + "/history?max_items=400")
        spans = job_spans(history)
    except (OSError, ValueError):
        history, spans = {}, {}
    nodes_file = os.path.join(folder, "nodes.json")  # ui_live.py: when ComfyUI started each node, from the page's WebSocket
    events = json.load(open(nodes_file)) if os.path.exists(nodes_file) else []
    graphs = {pid: (e.get("prompt") or [None, None, {}])[2] for pid, e in history.items()}
    names = {**{j["id"]: j["name"] for j in result["jobs"]}, **{job: name for name, job in FAILED_JOB.findall("\n".join(result["ended"]))}}
    result["nodes"], result["stopped_in"] = node_times(events, graphs, names), running_at_stop(events, graphs, names)
    try:  # the case's pictures: never a reason for the case to fail
        result["sheet"] = sheet(case, folder, os.path.join(a.comfy, "input", case["path"]) if case.get("path") else None,
                                mask=page_mask(a.comfy, t0), judge_at=quick_size(result["log"]))
    except Exception as exc:
        result["sheet"] = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    for job in result["jobs"]:  # when ComfyUI ran it, and the most memory held between those two times
        span = spans.get(job["id"])
        job["run"] = span[1] - span[0] if span else None
        job["vram"], job["ram"], job["own"] = memory.peak(*span) if span else [0, 0, 0]
    failed = [m for m in result["marks"] if m.startswith("FAILED")] or ([] if marks else ["ui_live.py wrote no marks"])
    done = any(m.startswith("downloaded") for m in result["marks"]) or not case.get("strokes")  # a fluid shot alone has no export
    result["passed"], result["why"] = not failed and done, (failed[0] if failed else "" if done else "the full-size composite was not reached: " + (result["marks"] or ["?"])[-1])
    if case.get("expect") == "name asked":  # an erase with no words on another object: no Klein pass, no shot (logic.asksName)
        result["passed"], result["why"] = name_asked(result["marks"], result["log"], result["jobs"])
    result["matte"] = matte_areas(a.comfy, t0) if any(s[0] == "paint" for s in case.get("strokes", [])) else None
    live = os.path.join(a.comfy, "temp", "paintaplate_live", "*.webp")
    result["live_files"] = sum(os.path.getmtime(f) >= t0 for f in glob.glob(live))
    return result


def report(a, machine, results):
    gpu, system = (machine.get("devices") or [{}])[0], machine.get("system", {})
    git = lambda *args: subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True).stdout.strip() or "unknown"  # noqa: E731
    gb = lambda n: f"{n / GB:.1f} GB"  # noqa: E731
    lines = ["# Paint a plate · GPU test report", "", "| | |", "| --- | --- |",
             f"| Written | {time.strftime('%d %B %Y, %H:%M')} (this machine's time) |",
             f"| GPU | {gpu.get('name', 'unknown')}, {gb(gpu.get('vram_total', 0))} of VRAM |",
             f"| RAM | {gb(system.get('ram_total', 0))} |",
             f"| ComfyUI | {system.get('comfyui_version', 'unknown')}, started with `{' '.join(system.get('argv', [])[1:]) or 'no flag'}` |",
             f"| PyTorch | {system.get('pytorch_version', 'unknown')} |",
             f"| Paint a plate | commit {git('rev-parse', '--short', 'HEAD')} on {git('rev-parse', '--abbrev-ref', 'HEAD')} |",
             f"| Cases | {a.cases}: {', '.join(r['name'] for r in results)} |",
             f"| Seeds | {a.seeds.replace(' ', '').replace(',', ', ') + ' (--seeds): each case runs once per seed' if a.seeds else 'each case runs from its own (gpu_matrix.json)'} |",
             "| Job index | left alone: the page is opened with `?index=0`, so every job runs |",
             f"| Memory profile asked for | {a.memory or 'none: the card decides'} |",
             f"| Before each case | {'ComfyUI is freed (--fresh)' if a.fresh else 'ComfyUI stays as the case before left it: a first job can read its RAM'} |",
             f"| RAM read from | {a.source} |", "",
             "Peak RAM is the most that was held; « no file » is the part of it that no file backs, which a memory cap cannot take back. "
             "In a job's row, Seconds runs from the page's request to the job's end, and In ComfyUI from its start to its end in "
             "ComfyUI's history. A job's peaks are the highest readings, once a second, between those two times.", "",
             "| Case | Result | Seconds | Peak VRAM | Peak RAM | No file | Memory stops retried | Previews received |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    ran = [r for r in results if not r.get("skipped")]  # the others were not started: ComfyUI had stopped
    for r in results:
        lines.append(f"| {r['name']} | not run: ComfyUI had stopped | | | | | | |" if r.get("skipped") else
                     f"| {r['name']} | {'passed' if r['passed'] else 'FAILED'} | {r['seconds']:.0f} | {gb(r['vram'])} | {gb(r['ram'])} | {gb(r['own'])} | {r['oom']} | {r['previews']} |")
    for r in ran:
        lines += ["", f"## {r['name']} · {'passed' if r['passed'] else 'FAILED'} in {r['seconds']:.0f} s", ""]
        if r["why"]:
            lines += [r["why"], ""]
        ann = r.get("announced", {})
        lines += ["| Step | Seconds | Announced | Seconds / announced |", "| --- | --- | --- | --- |",
                  *[f"| {label} | {s:.1f} | {ann.get(label, '')} | {f'{s / ann[label]:.2f}' if ann.get(label) else ''} |" for label, s in r["steps"]]]
        lines += ["", "| Job | Seconds | In ComfyUI | Peak VRAM | Peak RAM | No file | Nodes from ComfyUI's cache | Previews |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for j in r["jobs"]:
            in_comfy = "" if j["run"] is None else f"{j['run']:.1f}"
            peaks = " | | " if j["run"] is None else f"{gb(j['vram'])} | {gb(j['ram'])} | {gb(j['own'])}"
            lines.append(f"| {j['name']} {j['id']} | {j['seconds']:.1f} | {in_comfy} | {peaks} | {j['cached']} of {j['nodes']} | {j['previews']} |")
        lines += ["", f"- Memory profile: {r['profile']}.", f"- {seed_note(r.get('seed'), r['seeds'])}",
                  f"- Peak VRAM {gb(r['vram'])}. Peak RAM {gb(r['ram'])}, of which {gb(r['own'])} that no file backs"
                  + (f"; this container's own count, page cache included: {gb(r['container'])}" if r["container"] else "") + ".",
                  f"- Out-of-memory retries: {r['oom']}. Jobs taken from the job index, so not timed: {r['indexed']}.",
                  f"- Previews received by the page: {r['previews']}. Live previews written by the node: {r['live_files']}."
                  + ("".join(f" Live preview off: {why}." for why in r["live_off"]))]
        off = estimates_off(r["steps"], r.get("announced", {}))
        lines += [f"- Steps more than 25% from their announcement: {'; '.join(off)}." if off else "- Every announced step took within 25% of its announcement."]
        for j in r["jobs"]:  # where the long jobs' time went (D7): the five longest nodes
            spent = r.get("nodes", {}).get(j["id"])
            if spent and j["seconds"] >= 30:
                lines.append(f"- Where {j['name']} {j['id']}'s {j['seconds']:.1f} s went, by node: " + ", ".join(f"{c} {s:.1f} s" for c, s in spent[:5]) + ".")
        for name, job in FAILED_JOB.findall("\n".join(r.get("ended", []))):  # what ran before ComfyUI stopped, and what was running
            spent, at = r.get("nodes", {}).get(job), r.get("stopped_in", {}).get(job)
            if spent or at:
                lines.append(f"- {name} {job} before the stop, by node: " + (", ".join(f"{c} {s:.1f} s" for c, s in spent[:5]) or "none ended")
                             + (f". Running at the stop: {at}." if at else "."))
        lines += carried(r, a.fresh, gb)
        lines += [f"- The page's figure for an erase: {f}" for f in r.get("figures", [])]
        lines += [f"- HDR Match, in ComfyUI's log: {m.split('HDR Match:', 1)[1].strip()}" for m in r.get("hdr_match", [])]
        if not r.get("hdr_match") and render_hdr(r["steps"]):
            lines.append("- HDR Match: its line has left ComfyUI's log buffer; grep the terminal for « HDR Match ».")
        lines += [f"- Did not finish: {line}" for line in r["ended"]]
        lines += [f"- {m}" for m in r["mattes"]]
        if r["matte"]:
            folder, areas = r["matte"]
            ratios = [x / max(areas[0], 1e-9) for x in areas]
            worst = max(range(len(ratios)), key=lambda i: abs(ratios[i] - 1))
            lines += [f"- Paint matte read from `{os.path.relpath(folder, a.comfy)}`: {len(areas)} frames, the first covers {100 * areas[0]:.2f}% of the frame. "
                      f"Against the first frame, the area goes from {min(ratios):.2f} to {max(ratios):.2f} times; the furthest frame is {worst}, at {ratios[worst]:.2f} times.",
                      "- Every frame, against the first: " + " ".join(f"{x:.2f}" for x in ratios)]
        made = r.get("sheet")
        if made and made.get("path"):
            lines += [f"- The plate and the export around each edit, on frames {', '.join(map(str, made['frames']))}:", "",
                      f"  ![{r['name']}]({os.path.relpath(made['path'], a.out)})", ""]
            lines += [f"- The page's verdict on the export (logic.eraseCheck): {made['verdict']['text']}"] if made.get("verdict") else []
        elif made:
            lines.append(f"- No sheet: {made['error']}.")
        lines += [f"- Marks, screenshots, the page's log and the zip: `{os.path.relpath(r['folder'], a.out)}`."]
    failures = [r for r in ran if not r["passed"]]
    if failures:
        lines += ["", "## The log of each failure", ""]
        for r in failures:
            lines += [f"### {r['name']}", "", "```", *r["marks"][-12:], "...", *r["log"].splitlines()[-60:], "```", ""]
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8188", help="the running ComfyUI")
    ap.add_argument("--comfy", required=True, help="that ComfyUI's folder, on this machine")
    ap.add_argument("--out", required=True, help="a folder for the report and each case's files")
    ap.add_argument("--cases", default="quick", help="quick, all, or case names with commas: " + ", ".join(ALL))
    ap.add_argument("--channel", default="chrome", help="the browser channel: Google Chrome plays H.264")
    ap.add_argument("--timeout", type=int, default=900, help="ui_live.py's --timeout: it waits 8 times this many seconds for a render, 4 times for a fluid shot, twice for an edit")
    ap.add_argument("--memory", default="", choices=("", "small", "medium", "large"), help="ask the page for this memory profile; by default the card decides")
    ap.add_argument("--hdr", action="store_true", help="turn SDR to HDR on in every case (ui_live.py --hdr); a case asks for it with « hdr »: true")
    ap.add_argument("--graph", action="store_true", help="after each case's export, also save the scene's ComfyUI graph as scene.comfyui.json in the case's folder")
    ap.add_argument("--seeds", default="", help="whole numbers with commas: each case runs once per seed, as <case>_s<seed>, in place of its own seed")
    ap.add_argument("--fresh", action="store_true", help="free ComfyUI's memory before each case, so a case's peak RAM is its own; its first job then loads its models again")
    a = ap.parse_args()
    a.url, a.comfy, a.out = a.url.rstrip("/"), os.path.abspath(a.comfy), os.path.abspath(a.out)
    cases = load_cases()
    names = QUICK if a.cases == "quick" else ALL if a.cases == "all" else tuple(a.cases.split(","))
    unknown = [n for n in names if n not in cases]
    if unknown:
        stop(f"No such case: {', '.join(unknown)}. The cases are {', '.join(cases)}.")
    seeds = seeds_asked(a.seeds)
    browser_ready(a.channel)
    try:
        machine = get(a.url + "/system_stats")
    except OSError:
        stop(f"No ComfyUI answers at {a.url}: start it, then run this again.")
    pid = Memory(a.url).pid
    a.source = f"ComfyUI's process, {pid} (/proc/{pid}/status)" if pid else "the system's RAM in use (/system_stats): ComfyUI's process cannot be read from here"
    plates = os.path.join(a.comfy, "input", "plates")
    if any("path" in cases[n] for n in names) and not os.path.exists(os.path.join(plates, "horse.mp4")):
        stop("The test plate is missing: run `python get_plates.py` in the pack's folder, which puts horse.mp4 in ComfyUI's input/plates.")
    for file, fps in UHD.items():
        if any(cases[n].get("path", "").endswith(file) for n in names) and not os.path.exists(os.path.join(plates, file)):
            print(f"making {file} from horse.mp4", flush=True)
            make_uhd(os.path.join(plates, "horse.mp4"), os.path.join(plates, file), fps)
    hdr = os.path.join(plates, "horse_hdr")  # the HDR test plate: horse.mp4's frames as half-float EXR, lifted to a peak near 7
    if any(cases[n].get("path") == "plates/horse_hdr" for n in names) and not glob.glob(os.path.join(hdr, "horse_hdr.*.exr")):
        print("making the HDR test plate from horse.mp4 (tests/hdr_plate.py)", flush=True)
        import hdr_plate
        hdr_plate.make(os.path.join(plates, "horse.mp4"), hdr)
    os.makedirs(a.out, exist_ok=True)
    # one run per case, or per case and seed with --seeds: its name in the report and for its folder, and what it hands to the page
    left = [(name, cases[name]) if seed is None else (f"{name}_s{seed}", {**cases[name], "seed": seed}) for name in names for seed in seeds]
    results = []
    while left:
        name, case = left.pop(0)
        if a.fresh:
            free(a.url)
        results.append(run_case(a, name, case, os.path.join(a.out, name)))
        print(f"{name}: {'passed' if results[-1]['passed'] else 'FAILED'} in {results[-1]['seconds']:.0f} s", flush=True)
        if left and not answers(a.url):  # each case left would fail in 31 s with a traceback (the laptop, 12 Nov)
            print(f"ComfyUI has stopped. Not run: {', '.join(n for n, _ in left)}", flush=True)
            results += [{"name": n, "passed": False, "skipped": True} for n, _ in left]
            left = []
        report(a, machine, results)
    print(f"report: {os.path.join(a.out, 'report.md')}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
