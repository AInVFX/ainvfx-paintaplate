"""Opens one plate through the page's own `ingest` workflow on a running ComfyUI, and says what each node takes in memory.

    python tests/open_probe.py horse.mp4 [--url http://127.0.0.1:8188] [--fresh] [--csv readings.csv]

`plate` is the path the page sends: a video or a folder of frames under ComfyUI's input folder, or `output:<path>` under its
output folder. Run it with ComfyUI's own Python, or after `pip install -r tests/requirements.txt`.

1. It asks /paintaplate/stat for the plate and fills `ingest` with the values the page sends (openPlate, web/app.mjs).
2. It reads the memory four times a second. On ComfyUI's machine: what ComfyUI's process holds (VmRSS in /proc/<pid>/status),
   the most it ever held (VmHWM, which no reading can miss) and the count of its cgroup (memory.current: the container on a
   pod, the scope under systemd-run). From another machine: the RAM in use, as /system_stats reports it.
3. It listens to ComfyUI's websocket for the node that runs, and prints one row per node: the memory at its start, its
   peak, the memory at its end, its seconds. While the job runs, a line every five seconds says where the memory is and in
   which node: when ComfyUI is killed for its memory, the lines already printed name the node.

The frame and the movie it makes land in ComfyUI's output folder, under paintaplate/probe_<time>: delete them freely.
"""
import argparse
import asyncio
import functools
import json
import os
import sys
import threading
import time
import urllib.parse

import aiohttp
import av

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
from build_workflows import fill  # noqa: E402
from comfy_live import http  # noqa: E402

GB = 2 ** 30
RATE = 4  # readings of the memory a second
BEAT = 5  # seconds between two lines about a job that still runs
NATIVE_SIDE = 4096  # the long side of the playback movie, at most (web/app.mjs)
LOG_SPACE = "ACEScct"  # an image sequence's playback movie holds log values: the built-in config's choice (logic.viewerSpace)
CLIENT = "paintaplate-probe"
say = functools.partial(print, flush=True)


# ---------- The memory ----------

def _links(folder):
    try:
        names = os.listdir(folder)
    except OSError:  # another user's process, or one that has just ended
        return
    for name in names:
        try:
            yield os.readlink(os.path.join(folder, name))
        except OSError:
            pass


def listener_pid(port, proc="/proc"):
    """The process of this machine that listens on a TCP port: the socket's inode in /proc/net/tcp or tcp6, then the
    process that holds it. None when nothing listens there, or when the process belongs to another user."""
    sockets = set()
    for table in ("tcp", "tcp6"):
        try:
            with open(os.path.join(proc, "net", table)) as f:
                lines = f.read().splitlines()[1:]
        except OSError:
            continue
        for fields in map(str.split, lines):
            if len(fields) > 9 and fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port:  # 0A: it listens
                sockets.add(f"socket:[{fields[9]}]")
    for pid in sorted(int(p) for p in os.listdir(proc) if p.isdigit()) if sockets else ():
        if any(link in sockets for link in _links(os.path.join(proc, str(pid), "fd"))):
            return pid
    return None


def local_pid(url, proc="/proc"):
    """ComfyUI's process when its address is this machine's, else None."""
    u = urllib.parse.urlsplit(url)
    return listener_pid(u.port or 80, proc) if u.hostname in ("127.0.0.1", "localhost", "::1") else None


def status_bytes(pid, field, proc="/proc"):
    """One memory field of /proc/<pid>/status, in bytes: VmRSS is the RAM the process holds now, VmHWM the most it has held."""
    with open(os.path.join(proc, str(pid), "status")) as f:
        for line in f:
            if line.startswith(field + ":"):
                return int(line.split()[1]) * 1024
    raise OSError(f"process {pid} has no {field}: it has ended")


def cgroup_file(pid, proc="/proc", cgroups="/sys/fs/cgroup"):
    """The memory count of the cgroup a process runs in (memory.current of cgroup v2): the container's on a pod, the scope's
    under systemd-run. None where the kernel keeps no such count: the root of a machine, or cgroup v1."""
    try:
        with open(os.path.join(proc, str(pid), "cgroup")) as f:
            rel = next(line.split("::", 1)[1].strip() for line in f if line.startswith("0::"))
    except (OSError, StopIteration):
        return None
    path = os.path.join(cgroups, rel.lstrip("/"), "memory.current")
    return path if os.path.isfile(path) else None


class Process:
    """ComfyUI's own process, on this machine."""

    def __init__(self, pid, proc="/proc", cgroups="/sys/fs/cgroup"):
        self.pid, self.proc, self.group = pid, proc, cgroup_file(pid, proc, cgroups)
        with open(os.path.join(proc, str(pid), "cmdline"), "rb") as f:
            command = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
        self.name = f"process {pid} ({command[:90]}), VmRSS"

    def read(self):
        group = None
        if self.group:
            with open(self.group) as f:
                group = int(f.read())
        return status_bytes(self.pid, "VmRSS", self.proc), group

    def most(self):
        return status_bytes(self.pid, "VmHWM", self.proc)


class Machine:
    """The RAM in use on ComfyUI's machine, as /system_stats reports it: for a probe that runs on another machine. Inside a
    container it is the host's figure, so on a pod run the probe on the pod."""

    def __init__(self, url):
        self.url, self.name = url, "the RAM in use on ComfyUI's machine (/system_stats)"

    def read(self):
        system = http(f"{self.url}/system_stats", timeout=5)[0]["system"]
        return system["ram_total"] - system["ram_free"], None

    def most(self):
        return None


class Sampler(threading.Thread):
    """Reads the memory RATE times a second as (time, bytes, cgroup bytes), until stop() or until it cannot be read any more."""

    def __init__(self, source):
        super().__init__(daemon=True)
        self.source, self.samples, self.halt = source, [], threading.Event()

    def run(self):
        while not self.halt.is_set():
            try:
                self.samples.append((time.monotonic(), *self.source.read()))
            except (OSError, KeyError, TypeError, ValueError):  # the process has ended, or ComfyUI answers no more
                return
            self.halt.wait(1 / RATE)

    def stop(self):
        self.halt.set()
        self.join(5)


# ---------- The job ----------

class Job:
    """What ComfyUI says about one prompt: the node that runs and when, the nodes it took from its cache, how it ended."""

    def __init__(self, prompt):
        self.classes = {node: spec["class_type"] for node, spec in prompt.items()}
        self.id = self.posted = self.started = self.end = self.error = None
        self.events, self.cached = [], []  # events: (time, node), in the order ComfyUI ran them

    def take(self, message, t):
        """One websocket message, as ComfyUI sends it. True once the job has ended."""
        data = message.get("data") or {}
        if self.id is None or data.get("prompt_id") != self.id:
            return False
        kind = message.get("type")
        if kind == "execution_start":
            self.started = t
        elif kind == "execution_cached":
            self.cached = [str(node) for node in data.get("nodes") or []]
        elif kind == "executing" and data.get("node") is not None:
            self.events.append((t, str(data["node"])))
        elif kind in ("execution_success", "execution_error", "execution_interrupted"):
            self.end = t
            if kind == "execution_error":
                self.error = f"{data.get('node_type')}: {str(data.get('exception_message', '')).strip()[:300]}"
            elif kind == "execution_interrupted":
                self.error = "it was stopped"
            return True
        return False

    def node_at(self, t):
        """The node that ran at a time, as `node (class)`, or None before the first one."""
        ran = [node for at, node in self.events if at <= t]
        return f"node {ran[-1]} ({self.classes.get(ran[-1], '?')})" if ran else None


def span(samples, t0, t1):
    """(start, peak, end) of the memory between two times: the reading before t0, then every reading up to t1. A node
    shorter than the time between two readings takes the reading before it."""
    values = [v for t, v, _ in samples if t <= t0][-1:] + [v for t, v, _ in samples if t0 < t <= t1]
    values = values or [samples[0][1]]
    return values[0], max(values), values[-1]


def _row(node, name, memory, seconds):
    return f"{node:<5}{name[:33]:<34}" + "".join(f"{v / GB:8.1f}" for v in memory) + f"{seconds:9.1f}"


def table(samples, job, t0, t1):
    """The report's lines, in GB: one per node that ran, then the whole job from its post to its end."""
    lines = [f"{'node':<5}{'class':<34}{'start':>8}{'peak':>8}{'end':>8}{'seconds':>9}"]
    for i, (t, node) in enumerate(job.events):
        until = job.events[i + 1][0] if i + 1 < len(job.events) else t1
        lines.append(_row(node, job.classes.get(node, "?"), span(samples, t, until), until - t))
    lines.append(_row("", "the whole job", span(samples, t0, t1), t1 - t0))
    return lines


def page_values(path, st, run, config="", color_space="", proxy_space=""):
    """What openPlate (web/app.mjs) sends with `ingest`, from the answer of /paintaplate/stat: the plate's colour space as
    read from the file, and a playback movie at the plate's own size, up to NATIVE_SIDE on the long side."""
    k = min(1, NATIVE_SIDE / max(st["width"], st["height"]))
    w, h = int(st["width"] * k + 0.5), int(st["height"] * k + 0.5)  # display.nativeSize: Math.round
    cs = color_space or st["color_space"]
    return {"path": path, "config": config, "color_space": cs,
            "proxy_space": proxy_space or (cs if st["kind"] == "video" else LOG_SPACE),
            "proxy_size": max(w, h), "movie_width": w - w % 2, "movie_height": h - h % 2,
            "prefix": f"{run}/hero", "video_prefix": f"{run}/proxy"}


def versions(stats):
    system, devices = stats.get("system") or {}, stats.get("devices") or []
    names = (("ComfyUI", "comfyui_version"), ("Python", "python_version"), ("PyTorch", "pytorch_version"))
    parts = [f"{label} {str(system[key]).split()[0]}" for label, key in names if system.get(key)]
    if system.get("ram_total"):
        parts.append(f"{system['ram_total'] / GB:.1f} GB of RAM")
    if devices and devices[0].get("vram_total"):
        parts.append(f"{devices[0]['vram_total'] / GB:.0f} GB of VRAM")
    return ", ".join(parts) or "no version reported"


async def _beats(job, sampler):
    while True:
        await asyncio.sleep(BEAT)
        t, held = sampler.samples[-1][:2]
        say(f"  {t - job.posted:5.0f} s: {held / GB:.1f} GB, in {job.node_at(t) or 'the queue'}")


async def follow(url, prompt, job, sampler):
    """Posts the prompt once the websocket is open, then hears ComfyUI until the job ends. False when the workflow is
    refused, or when ComfyUI stops answering before the end."""
    async with aiohttp.ClientSession() as session, session.ws_connect(f"ws{url[4:]}/ws?clientId={CLIENT}", max_msg_size=0) as ws:
        answer, _ = http(f"{url}/prompt", {"prompt": prompt, "client_id": CLIENT})
        if not isinstance(answer, dict) or "prompt_id" not in answer:
            job.error = f"ComfyUI refused the workflow: {json.dumps(answer)[:600] if isinstance(answer, dict) else answer[:300]}"
            return False
        job.id, job.posted = answer["prompt_id"], time.monotonic()
        beats = asyncio.create_task(_beats(job, sampler))
        try:
            async for message in ws:
                if message.type is aiohttp.WSMsgType.TEXT and job.take(json.loads(message.data), time.monotonic()):
                    return True
            return False
        finally:
            beats.cancel()


def write_csv(path, samples, job):
    with open(path, "w") as f:
        f.write("seconds,bytes,cgroup_bytes,node\n")
        for t, held, group in samples:
            node = ([n for at, n in job.events if at <= t] or [""])[-1]
            f.write(f"{t - job.posted:.2f},{held},{'' if group is None else group},{node}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plate", help="the plate as the page names it: a path under ComfyUI's input folder, or output:<path>")
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--pid", type=int, help="ComfyUI's process, when the probe does not find it from the port")
    ap.add_argument("--remote", action="store_true", help="read the memory from /system_stats, also on ComfyUI's machine")
    ap.add_argument("--config", default="", help="the OCIO config the page sends (default: the built-in one)")
    ap.add_argument("--color-space", default="", help="the plate's colour space (default: read from the file, as the page does)")
    ap.add_argument("--proxy-space", default="", help=f"the playback movie's colour space (default: the plate's for a video, {LOG_SPACE} for frames)")
    ap.add_argument("--max-frames", type=int, help="the page sends none: the workflow's own 121")
    ap.add_argument("--fresh", action="store_true", help="first POST /free: ComfyUI drops its cached results, and unloads its models")
    ap.add_argument("--settle", type=float, default=5, help="seconds of readings after the job, for what stays (default 5)")
    ap.add_argument("--limit", type=float, default=1800, help="seconds before the probe stops waiting (default 1800)")
    ap.add_argument("--csv", help="write every reading to this file: seconds, bytes, cgroup bytes, node")
    a = ap.parse_args(argv)
    url = a.url.rstrip("/")
    try:
        stats, _ = http(f"{url}/system_stats", timeout=10)
    except OSError as exc:
        say(f"No ComfyUI answers at {url}: {exc}")
        return 1
    st, _ = http(f"{url}/paintaplate/stat?{urllib.parse.urlencode({'path': a.plate, 'config': a.config, 'cs': a.color_space})}")
    if not isinstance(st, dict) or "width" not in st:
        say(f"ComfyUI cannot read {a.plate}: {st.get('error') if isinstance(st, dict) else 'nothing answers at /paintaplate/stat'}")
        return 1
    values = page_values(a.plate, st, f"paintaplate/probe_{int(time.time())}", a.config, a.color_space, a.proxy_space)
    if a.max_frames:
        values["max_frames"] = a.max_frames
    prompt = fill("ingest", values)
    frames = min(st.get("frames") or 121, a.max_frames or 121)
    copy = st["width"] * st["height"] * frames * 12  # float32 RGB
    say(f"Open probe: {a.plate} on {url} ({versions(stats)})")
    say(f"This Python: PyAV {av.__version__}, libavcodec {'.'.join(map(str, av.library_versions['libavcodec']))}. ComfyUI's own Python gives ComfyUI's figures")
    say(f"Plate: {st.get('kind')} {st.get('codec') or st.get('ext') or ''} {st.get('pix_fmt') or ''}, {st['width']} x {st['height']}, "
        f"{frames} frames, {values['color_space']}. One float32 copy of its frames: {copy / GB:.2f} GB")
    if a.fresh:
        http(f"{url}/free", {"free_memory": True})
        time.sleep(2)
        say("ComfyUI was asked to drop its cached results and to unload its models (POST /free)")
    try:
        pid = None if a.remote else a.pid or local_pid(url)
        source = Process(pid) if pid else Machine(url)
    except OSError as exc:
        say(f"Process {pid} cannot be read: {exc}")
        return 1
    sampler = Sampler(source)
    sampler.start()
    time.sleep(1)
    if not sampler.samples:
        say(f"The memory cannot be read from {source.name}")
        return 1
    before, most_before = sampler.samples[-1], source.most()
    say(f"Memory: {source.name}, {RATE} readings a second. Before the job: {before[1] / GB:.1f} GB")
    job = Job(prompt)
    try:
        ended = asyncio.run(asyncio.wait_for(follow(url, prompt, job, sampler), a.limit))
    except asyncio.TimeoutError:
        ended, job.error = False, f"it still ran after {a.limit:.0f} s"
    except (aiohttp.ClientError, OSError) as exc:
        ended, job.error = False, f"ComfyUI stopped answering ({type(exc).__name__})"
    if job.posted is None:
        sampler.stop()
        say(job.error or "The websocket did not open")
        return 1
    if ended:
        time.sleep(a.settle)
    sampler.stop()
    samples = sampler.samples
    t1 = job.end or samples[-1][0]
    if job.started and job.started - job.posted > 1:
        say(f"The job waited {job.started - job.posted:.1f} s in ComfyUI's queue")
    say("\n".join(table(samples, job, job.posted, t1)))
    peak = span(samples, job.posted, t1)[1]
    peak_at = next(t for t, v, _ in samples if v == peak and t <= t1)
    say(f"Peak: {peak / GB:.1f} GB, {(peak - before[1]) / GB:.1f} GB above the level before the job, or {(peak - before[1]) / copy:.1f} copies "
        f"of the plate, in {job.node_at(peak_at) or 'the job'}")
    if ended:
        after, stays = samples[-1][1], samples[-1][1] - before[1]
        say(f"{a.settle:.0f} s after the job: {after / GB:.1f} GB, " + (f"{stays / GB:.1f} GB above the level before, or {stays / copy:.1f} copies"
                                                                     if stays > 0.05 * GB else "the level before the job"))
    try:
        most = source.most()
    except OSError:
        most = None
    if most:
        say(f"The most the process ever held (VmHWM): {most / GB:.1f} GB, " + ("reached during this job" if most > most_before else "reached before this job"))
    groups = [g for t, _, g in samples if g is not None and job.posted <= t <= t1]
    if groups:
        say(f"Its cgroup, which also counts the file cache and the other processes (memory.current): {before[2] / GB:.1f} GB before, "
            f"{max(groups) / GB:.1f} GB at the peak, {samples[-1][2] / GB:.1f} GB at the end")
    if job.cached:
        say(f"{len(job.cached)} of {len(prompt)} nodes came from ComfyUI's cache and did not run ({', '.join(sorted(job.cached, key=lambda n: (len(n), n)))}): "
            "run again with --fresh for a full measure")
    if a.csv:
        write_csv(a.csv, samples, job)
    if not ended or job.error:
        say(f"The job did not finish: {job.error or 'ComfyUI stopped answering'}, {t1 - job.posted:.1f} s after the post, in "
            f"{job.node_at(t1) or 'the queue'}. The table holds what was read until then")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
