"""One GPU test for a pod and for a laptop: the real page over a list of cases, and one report.

    python tests/gpu_matrix.py --url http://127.0.0.1:8188 --comfy <ComfyUI folder> --out <folder> --cases quick

Each case runs tests/ui_live.py on a running ComfyUI (the real page, in Google Chrome). This script then reads what the
case left behind and writes <out>/report.md: the machine, then per case the time of each step (the page's log times
every step), peak VRAM and RAM (ComfyUI's /system_stats, every second), out-of-memory retries, the memory profile, the
paint matte's area on every frame against the first frame's, the previews received, pass or fail, then the log of each
failure. The report is written again after every case, so a run that is stopped still leaves one.

quick: on plates/horse.mp4 (tools/get_plates.sh) a cow painted behind the fence, one erase, one light, then a fluid shot
at 1280 x 704 x 121. all adds a 3840 x 2160 plate at 50 fps, made here from horse.mp4 (paint, erase, light), and a fluid
shot at 1920 x 1088 at 50 fps with one edit on it. --cases also takes case names, with commas. The strokes are in
gpu_matrix.json beside this file. Every run moves them by a fraction of a pixel, so no job comes back from the job index
and every time is a real one; --exact keeps them as written. --memory small, medium or large asks the page for that memory
profile (logic.memoryProfile) in place of the one the card gives: the same case under two profiles shows what a profile costs.

It needs Playwright with Google Chrome: Playwright's own Chromium cannot play H.264. Run it on the machine that runs
ComfyUI, with a Python that has Pillow and numpy (ComfyUI's own has both): it reads the mattes and the live previews in
ComfyUI's output and temp folders.
"""
import argparse
import glob
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
QUICK = ("horse_cow", "horse_erase", "horse_light", "fluid_720")
ALL = QUICK + ("uhd_cow", "uhd_erase", "uhd_light", "fluid_1080_edit")
UHD = {"file": "horse_3840x2160_50fps.mp4", "size": (3840, 2160), "fps": 50, "frames": 121}  # « 4K at 50 fps »: every tool runs on it
STEP = re.compile(r"Render v(\d+): (.+?) took ([\d.]+) s")  # the page's log: one line per render step
JOB = re.compile(r"([a-z]+) [0-9a-f?]{1,8}: done in ([\d.]+) s")  # and one per finished job; a line starts with its time, with no space after it
CACHED = re.compile(r"([a-z]+) [0-9a-f?]{1,8}: (\d+) of (\d+) nodes from ComfyUI's cache")  # a model loader among them is a model not loaded again
GB = 2 ** 30


def stop(sentence):
    print(sentence)
    sys.exit(2)


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Paint a plate gpu_matrix)"})  # Runpod's proxy refuses urllib's own
    with urllib.request.urlopen(request, timeout=10) as r:
        return json.load(r)


class Memory(threading.Thread):
    """Peak VRAM and RAM in use while a case runs: ComfyUI's /system_stats every second, and in a container its own count
    (/sys/fs/cgroup/memory.current), since /system_stats reports the host's RAM there."""
    CGROUP = "/sys/fs/cgroup/memory.current"

    def __init__(self, url):
        super().__init__(daemon=True)
        self.url, self.vram, self.ram, self.container, self.on = url, 0, 0, 0, True

    def run(self):
        while self.on:
            try:
                stats = get(self.url + "/system_stats")
                gpu = (stats.get("devices") or [{}])[0]
                self.vram = max(self.vram, gpu.get("vram_total", 0) - gpu.get("vram_free", 0))
                self.ram = max(self.ram, stats["system"].get("ram_total", 0) - stats["system"].get("ram_free", 0))
                if os.path.exists(self.CGROUP):
                    with open(self.CGROUP) as f:
                        self.container = max(self.container, int(f.read()))
            except (OSError, ValueError, KeyError):
                pass  # ComfyUI is busy or restarting: the next second asks again
            time.sleep(1)


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


def make_uhd(source, target, spec=UHD):
    """The 3840 x 2160 plate at 50 fps: horse.mp4's first 121 frames, enlarged with Lanczos by the pack's own movie writer."""
    try:
        import av
    except ImportError:
        stop("PyAV is missing: run this script with ComfyUI's own Python, or `pip install av`.")
    sys.path.insert(0, REPO)
    import plateio
    with av.open(source) as src:
        frames = [f.to_ndarray(format="rgb24") for _, f in zip(range(spec["frames"]), src.decode(video=0))]
    plateio.write_movie(lambda i: frames[i], len(frames), target, spec["fps"], crf=14, preset="medium", size=spec["size"])


def moved(strokes, exact):
    """The strokes with every point moved by at most 0.002 of the frame: new jobs, so nothing comes from the job index."""
    if exact:
        return strokes
    out = json.loads(json.dumps(strokes))
    for stroke in out:  # a stroke is [key, words, points, ...]; a fluid keyframe is [frame, colour, points, ...]
        stroke[2] = [[min(1.0, max(0.0, v + random.uniform(-0.002, 0.002))) for v in point] for point in stroke[2]]
    return out


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


def read_log(text):
    """What a case's page log says: the render steps and the jobs with their seconds, and the counts the report shows."""
    profile = re.search(r"Memory profile (\w+): ([^\n]*)", text)
    return {
        "steps": [(f"v{v} {label}", float(s)) for v, label, s in STEP.findall(text)],
        "jobs": [(name, float(s)) for name, s in JOB.findall(text)],
        "cached": [(name, int(k), int(n)) for name, k, n in CACHED.findall(text)],
        "indexed": text.count("taken from the job index"),
        "oom": text.count("ran out of memory"),
        "previews": sum(int(n) for n in re.findall(r"(\d+) preview\(s\) received", text)),
        "live_off": re.findall(r"Live preview is off: ([^\n]*)", text),
        "profile": f"{profile.group(1)} ({profile.group(2)})" if profile else "not in the log's last 400 lines",
        "mattes": re.findall(r"((?:Paint|Erase) matte[^\n]*largest matte is [^\n]*)", text),
    }


def run_case(a, name, case, folder):
    cmd = [sys.executable, os.path.join(HERE, "ui_live.py"), "--url", a.url, "--comfy", a.comfy, "--out", folder,
           "--channel", a.channel, "--timeout", str(a.timeout), "--think", "2", *(["--memory", a.memory] if a.memory else [])]
    if "fluid" in case:
        cmd += ["--fluid", json.dumps({**case["fluid"], "keys": moved(case["fluid"]["keys"], a.exact)})]
    else:
        cmd += ["--path", case["path"]]
    if case.get("strokes"):
        cmd += ["--strokes", json.dumps(moved(case["strokes"], a.exact))]
    memory, t0 = Memory(a.url), time.time()
    memory.start()
    print(f"--- {name}", flush=True)
    subprocess.run(cmd)
    memory.on = False
    result = {"name": name, "seconds": time.time() - t0, "vram": memory.vram, "ram": memory.ram, "container": memory.container, "folder": folder}
    log_file, marks_file = os.path.join(folder, "page_log.txt"), os.path.join(folder, "timings.json")
    result["log"] = open(log_file, encoding="utf-8").read() if os.path.exists(log_file) else ""
    marks = json.load(open(marks_file)).get("marks", []) if os.path.exists(marks_file) else []
    result["marks"] = [what for _, what in marks]
    result.update(read_log(result["log"]))
    failed = [m for m in result["marks"] if m.startswith("FAILED")] or ([] if marks else ["ui_live.py wrote no marks"])
    done = any(m.startswith("downloaded") for m in result["marks"]) or not case.get("strokes")  # a fluid shot alone has no export
    result["passed"], result["why"] = not failed and done, (failed[0] if failed else "" if done else "the full-size composite was not reached: " + (result["marks"] or ["?"])[-1])
    result["matte"] = matte_areas(a.comfy, t0) if any(s[0] == "b" for s in case.get("strokes", [])) else None
    live = os.path.join(a.comfy, "temp", "paintaplate_live", "*.webp")
    result["live_files"] = sum(os.path.getmtime(f) >= t0 for f in glob.glob(live))
    return result


def report(a, machine, results):
    gpu, system = (machine.get("devices") or [{}])[0], machine.get("system", {})
    git = lambda *args: subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True).stdout.strip() or "unknown"  # noqa: E731
    lines = ["# Paint a plate · GPU test report", "", "| | |", "| --- | --- |",
             f"| Written | {time.strftime('%d %B %Y, %H:%M')} (this machine's time) |",
             f"| GPU | {gpu.get('name', 'unknown')}, {gpu.get('vram_total', 0) / GB:.1f} GB of VRAM |",
             f"| RAM | {system.get('ram_total', 0) / GB:.1f} GB |",
             f"| ComfyUI | {system.get('comfyui_version', 'unknown')}, started with `{' '.join(system.get('argv', [])[1:]) or 'no flag'}` |",
             f"| PyTorch | {system.get('pytorch_version', 'unknown')} |",
             f"| Paint a plate | commit {git('rev-parse', '--short', 'HEAD')} on {git('rev-parse', '--abbrev-ref', 'HEAD')} |",
             f"| Cases | {a.cases}: {', '.join(r['name'] for r in results)} |",
             f"| Memory profile asked for | {a.memory or 'none: the card decides'} |", "",
             "| Case | Result | Seconds | Peak VRAM | Peak RAM | Memory stops retried | Previews received |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r['name']} | {'passed' if r['passed'] else 'FAILED'} | {r['seconds']:.0f} | {r['vram'] / GB:.1f} GB | {r['ram'] / GB:.1f} GB | {r['oom']} | {r['previews']} |")
    for r in results:
        lines += ["", f"## {r['name']} · {'passed' if r['passed'] else 'FAILED'} in {r['seconds']:.0f} s", ""]
        if r["why"]:
            lines += [r["why"], ""]
        lines += ["| Step | Seconds |", "| --- | --- |", *[f"| {label} | {s:.1f} |" for label, s in r["steps"]]]
        per = {}
        for name, s in r["jobs"]:
            per.setdefault(name, []).append(s)
        cached = {}
        for name, k, n in r["cached"]:
            cached.setdefault(name, []).append(f"{k} of {n}")
        lines += ["", "| Workflow | Jobs | Seconds in all | Each job's seconds | Nodes from ComfyUI's cache, per job |", "| --- | --- | --- | --- | --- |",
                  *[f"| {n} | {len(v)} | {sum(v):.1f} | {', '.join(f'{s:.1f}' for s in v)} | {', '.join(cached.get(n, [])) or 'none'} |" for n, v in per.items()], ""]
        lines += [f"- Memory profile: {r['profile']}.",
                  f"- Peak VRAM {r['vram'] / GB:.1f} GB, peak RAM {r['ram'] / GB:.1f} GB" + (f" (this container: {r['container'] / GB:.1f} GB)" if r["container"] else "") + ".",
                  f"- Out-of-memory retries: {r['oom']}. Jobs taken from the job index, so not timed: {r['indexed']}.",
                  f"- Previews received by the page: {r['previews']}. Live previews written by the node: {r['live_files']}."
                  + ("".join(f" Live preview off: {why}." for why in r["live_off"]))]
        lines += [f"- {m}" for m in r["mattes"]]
        if r["matte"]:
            folder, areas = r["matte"]
            ratios = [x / max(areas[0], 1e-9) for x in areas]
            worst = max(range(len(ratios)), key=lambda i: abs(ratios[i] - 1))
            lines += [f"- Paint matte read from `{os.path.relpath(folder, a.comfy)}`: {len(areas)} frames, the first covers {100 * areas[0]:.2f}% of the frame. "
                      f"Against the first frame, the area goes from {min(ratios):.2f} to {max(ratios):.2f} times; the furthest frame is {worst}, at {ratios[worst]:.2f} times.",
                      "- Every frame, against the first: " + " ".join(f"{x:.2f}" for x in ratios)]
        lines += [f"- Marks, screenshots, the page's log and the zip: `{os.path.relpath(r['folder'], a.out)}`."]
    failures = [r for r in results if not r["passed"]]
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
    ap.add_argument("--exact", action="store_true", help="the strokes as written: jobs made before come back from the job index")
    a = ap.parse_args()
    a.url, a.comfy, a.out = a.url.rstrip("/"), os.path.abspath(a.comfy), os.path.abspath(a.out)
    with open(os.path.join(HERE, "gpu_matrix.json"), encoding="utf-8") as f:
        cases = json.load(f)
    names = QUICK if a.cases == "quick" else ALL if a.cases == "all" else tuple(a.cases.split(","))
    unknown = [n for n in names if not isinstance(cases.get(n), dict)]
    if unknown:
        stop(f"No such case: {', '.join(unknown)}. The cases are {', '.join(ALL)}.")
    browser_ready(a.channel)
    try:
        machine = get(a.url + "/system_stats")
    except OSError:
        stop(f"No ComfyUI answers at {a.url}: start it, then run this again.")
    plates = os.path.join(a.comfy, "input", "plates")
    if any("path" in cases[n] for n in names) and not os.path.exists(os.path.join(plates, "horse.mp4")):
        stop(f"The test plate is missing: run `bash tools/get_plates.sh {a.comfy}`, which puts horse.mp4 in input/plates.")
    if any(cases[n].get("path", "").endswith(UHD["file"]) for n in names) and not os.path.exists(os.path.join(plates, UHD["file"])):
        print(f"making {UHD['file']} from horse.mp4", flush=True)
        make_uhd(os.path.join(plates, "horse.mp4"), os.path.join(plates, UHD["file"]))
    os.makedirs(a.out, exist_ok=True)
    results = []
    for name in names:
        results.append(run_case(a, name, cases[name], os.path.join(a.out, name)))
        report(a, machine, results)
        print(f"{name}: {'passed' if results[-1]['passed'] else 'FAILED'} in {results[-1]['seconds']:.0f} s", flush=True)
    print(f"report: {os.path.join(a.out, 'report.md')}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
