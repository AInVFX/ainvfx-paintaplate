"""The page's HTTP routes: the export download, the plate browser of the Open dialog, and the blank plate.

    GET /paintaplate/download?run=paintaplate/<plate>/v3&name=shot010_paintaplate_v3&parts=export,matte
    GET /paintaplate/plates                      the plates in input/plates, as JSON (see list_plates)
    GET /paintaplate/thumb?path=plates/boat.mp4  the first frame of one of them as a small JPEG, cached in temp
    POST /paintaplate/blank {width, height, fps, frames}  a black ProRes 4444 plate in input/paintaplate/blank, for a fluid shot
    GET /paintaplate/jobs/<key>                  what a finished job with these inputs made, if its files are all still there (else outputs null)
    POST /paintaplate/jobs/<key> {workflow, outputs}  record a finished job, by the hash of its inputs (output/paintaplate/jobs)
    GET /paintaplate/stat?path=plates/boat.mp4   the size and time of a plate: a job index key changes when the plate does

`parts` chooses what the zip holds (default: export,matte): export is the result in the plate's own
format, matte where the plate changed, review an H.264 MP4 of the result (the export's full-size movie,
else the preview composite), shot the whole frame as the model made it (the full-size pass first). Only run folders under output/paintaplate are read, and only plain files inside
them: a symbolic link is skipped. The zip functions are plain Python (tests/test_routes.py);
setup() adds the routes to ComfyUI's server. The plate browser reads only input/plates (never a link out of it),
and its thumbnails are plain functions too (list_plates, thumbnail).
"""
from __future__ import annotations

import asyncio
import contextlib
import glob
import hashlib
import json
import logging
import os
import re
import uuid
import zipfile

import folder_paths
from aiohttp import web

try:
    from . import plateio
except ImportError:  # imported as a plain module by the tests, outside the package
    import plateio

PLATES = "plates"  # the folder under ComfyUI's input folder that the Open dialog lists
BLANK = "paintaplate/blank"  # and the one that holds the black canvases of fluid shots
THUMB_WIDTH = 240

# part: (paths in the run folder, the first match wins for a file; its name in the zip, None for a folder).
# The page keeps each preview size's composite and passes in a folder named after the size (640x352/), the
# full-size passes in full/, and the export's review movie at the top; the last patterns read older runs.
PARTS = {"export": (["export"], None), "matte": (["matte"], None),
         "review": (["review_*.mp4", "*/comp_*.mp4", "comp_*.mp4"], "review.mp4"),
         "shot": (["full/raw_*.mp4", "full/clean_*.mp4", "*/raw_*.mp4", "*/clean_*.mp4", "full_*.mp4", "raw_*.mp4"],
                  "regenerated_shot.mp4")}
DEFAULT_PARTS = ["export", "matte"]


def run_folder(rel: str) -> str:
    """The run folder `rel` names under output/paintaplate. FileNotFoundError for any other path."""
    out = os.path.abspath(folder_paths.get_output_directory())
    root = os.path.join(out, "paintaplate")
    full = os.path.abspath(os.path.join(out, rel))
    if os.path.commonpath([full, root]) != root or full == root or not os.path.isdir(full):
        raise FileNotFoundError("No export at this path")
    return full


def zip_name(name: str, folder: str) -> str:
    """A file name made only of letters, digits, '.', '-' and '_'."""
    return re.sub(r"[^\w.-]", "_", name or os.path.basename(folder))[:120]


def collect(folder: str, parts: list[str]) -> list[tuple[str, str]]:
    """(path on disk, name in the zip) for each part asked for, in a fixed order."""
    def inside(path):
        return not os.path.islink(path) and os.path.commonpath([os.path.realpath(path), folder]) == folder

    files = []
    for part in [p for p in PARTS if p in parts]:
        patterns, single = PARTS[part]
        if single is None:  # a folder, kept as a folder
            files += [(path, os.path.relpath(path, folder))
                      for d, _, names in os.walk(os.path.join(folder, patterns[0]))
                      for path in (os.path.join(d, f) for f in sorted(names)) if inside(path)]
            continue
        found = next((m for pat in patterns for m in sorted(glob.glob(os.path.join(folder, pat))) if inside(m)), None)
        if found:
            files.append((found, single))
    return files


def build_zip(folder: str, name: str, parts: list[str]) -> str:
    """The zip of `parts`, stored (EXR, PNG and video are already compressed) and reused while it is current."""
    files = collect(folder, parts)
    if not any(arc.startswith("export/") for _, arc in files):
        raise FileNotFoundError("This run has no export yet")
    target = os.path.join(folder, f"{name}__{'-'.join(p for p in PARTS if p in parts)}.zip")
    newest = max(os.path.getmtime(p) for p, _ in files)
    if os.path.exists(target) and os.path.getmtime(target) >= newest:
        return target
    part = f"{target}.{uuid.uuid4().hex}.part"  # two downloads at once never write the same file
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for path, arc in sorted(files, key=lambda f: f[1]):
                z.write(path, arc)
        os.replace(part, target)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return target


async def download(request: web.Request) -> web.StreamResponse:
    asked = [p for p in request.query.get("parts", "").split(",") if p in PARTS] or DEFAULT_PARTS
    try:
        folder = run_folder(request.query.get("run", ""))
        name = zip_name(request.query.get("name", ""), folder)
        path = await asyncio.to_thread(build_zip, folder, name, asked)
    except FileNotFoundError as exc:
        raise web.HTTPNotFound(text=str(exc)) from exc
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


# ---------- The plate browser ----------

def input_path(rel: str) -> str:
    """The file or folder `rel` names under ComfyUI's input folder. FileNotFoundError for any other path."""
    root = os.path.abspath(folder_paths.get_input_directory())
    full = os.path.abspath(os.path.join(root, rel))
    if os.path.isabs(rel) or os.path.commonpath([full, root]) != root or full == root or os.path.islink(full) or not os.path.exists(full):
        raise FileNotFoundError("No plate at this path")
    return full


def list_plates() -> list[dict]:
    """The plates in input/plates, each with what the Open dialog shows and sends: path, kind, size, frames, fps."""
    root = os.path.join(os.path.abspath(folder_paths.get_input_directory()), PLATES)
    if not os.path.isdir(root):
        return []
    items = []
    for name in sorted(os.listdir(root), key=str.lower):
        full = os.path.join(root, name)
        if os.path.islink(full) or name.startswith("."):
            continue
        is_dir, ext = os.path.isdir(full), os.path.splitext(name)[1].lower()
        if not is_dir and ext not in plateio.VIDEO_EXTS:
            continue
        try:
            spec = plateio.probe_plate(full)
        except Exception as exc:  # a folder without frames, a file PyAV cannot open: skipped, never fatal
            logging.info("PaintAPlate: %s skipped in input/%s: %s", name, PLATES, exc)
            continue
        items.append({"path": f"{PLATES}/{name}", "name": name, "kind": spec["kind"], "ext": spec.get("ext", ""),
                      "width": spec.get("width", 0), "height": spec.get("height", 0), "frames": spec.get("frames", 0),
                      "fps": round(float(spec.get("fps") or 0), 3), "color_space": plateio.guess_color_space(spec),
                      "mtime": int(os.path.getmtime(full))})
    return items


def thumbnail(rel: str, width: int = THUMB_WIDTH) -> str:
    """A JPEG of a plate's first frame, `width` wide, written once to temp/paintaplate_thumbs and reused."""
    import numpy as np
    from PIL import Image

    full = input_path(rel)
    first = plateio.find_sequence(full)[0] if os.path.isdir(full) else full
    folder = os.path.join(folder_paths.get_temp_directory(), "paintaplate_thumbs")
    os.makedirs(folder, exist_ok=True)
    key = hashlib.sha1(f"{full}|{os.path.getmtime(first)}|{width}".encode()).hexdigest()[:20]
    target = os.path.join(folder, f"{key}.jpg")
    if os.path.exists(target):
        return target
    with plateio.av.open(first) as c:
        frame = next(c.decode(video=0))
        if os.path.splitext(first)[1].lower() == ".exr":  # scene-linear float: a display transform for the thumbnail
            lin = np.clip(frame.to_ndarray(format="gbrpf32le")[..., :3], 0.0, None)
            srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(np.minimum(lin, 1.0), 1 / 2.4) - 0.055)
            img = Image.fromarray((np.clip(srgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
        else:
            img = frame.to_image()
    img.thumbnail((width, width))
    part = f"{target}.{uuid.uuid4().hex}.part"
    img.convert("RGB").save(part, "JPEG", quality=80)
    os.replace(part, target)
    return target


async def plates(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(list_plates))


async def thumb(request: web.Request) -> web.StreamResponse:
    try:
        path = await asyncio.to_thread(thumbnail, request.query.get("path", ""))
    except (FileNotFoundError, StopIteration, ValueError, OSError) as exc:
        raise web.HTTPNotFound(text=f"No thumbnail: {exc}") from exc
    return web.FileResponse(path, headers={"Cache-Control": "max-age=3600"})


# ---------- The blank plate of a fluid shot ----------

def blank_plate(width: int, height: int, fps: float, frames: int) -> str:
    """The input-folder path of a black plate of this size, frame rate and length, written once (ProRes 4444).

    LTX and ainvfx-fluid need sides in multiples of 64 and 8k + 1 frames; the page keeps to the trained limits.
    """
    if not (64 <= width <= 4096 and 64 <= height <= 4096 and width % 64 == 0 and height % 64 == 0):
        raise ValueError("width and height must be multiples of 64, from 64 to 4096")
    if not (9 <= frames <= 1025 and (frames - 1) % 8 == 0):
        raise ValueError("the length must be 8k + 1 frames, from 9 to 1025")
    if not 1 <= fps <= 120:
        raise ValueError("the frame rate must be from 1 to 120")
    rel = f"{BLANK}/fluid_{width}x{height}_{fps:g}fps_{frames}f.mov"
    full = os.path.join(os.path.abspath(folder_paths.get_input_directory()), rel)
    if not os.path.exists(full):
        os.makedirs(os.path.dirname(full), exist_ok=True)
        part = f"{full[:-4]}.{uuid.uuid4().hex}.mov"  # the muxer reads the format from the extension
        try:
            plateio.write_blank(part, width, height, fps, frames)
            os.replace(part, full)
        finally:
            if os.path.exists(part):
                os.remove(part)
    return rel


async def blank(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        rel = await asyncio.to_thread(blank_plate, int(body["width"]), int(body["height"]), float(body["fps"]), int(body["frames"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text=f"No blank plate: {exc}") from exc
    return web.json_response({"path": rel})


# ---------- The job index: a finished job's outputs, by the hash of everything that went into it ----------
# The page hashes a job's workflow and inputs (logic.indexValues) and asks here before it posts the job. A record holds only
# while every file it names is still a plain file in the output folder: a deleted file means the job runs again.
JOBS = "paintaplate/jobs"
JOB_KEY = re.compile(r"^[0-9a-f]{32,64}$")
JOB_MAX = 1 << 20  # bytes of one record


def job_path(key: str) -> str:
    """Where the record of `key` lives. ValueError for anything but a lowercase hex hash."""
    if not isinstance(key, str) or not JOB_KEY.match(key):
        raise ValueError("Not a job key")
    return os.path.join(folder_paths.get_output_directory(), JOBS, f"{key}.json")


def record_files(outputs: dict) -> list:
    """The files a record names, as ComfyUI's history lists them."""
    return [f for o in outputs.values() if isinstance(o, dict) for k in ("images", "gifs", "video") for f in (o.get(k) or [])]


def output_file(f) -> str | None:
    """The path of one file a record names, when it is a plain file inside the output folder; else None."""
    if not isinstance(f, dict) or f.get("type") != "output":
        return None
    out = os.path.abspath(folder_paths.get_output_directory())
    name, sub = str(f.get("filename") or ""), str(f.get("subfolder") or "")
    full = os.path.abspath(os.path.join(out, sub, name))
    if not name or os.path.isabs(sub) or os.path.commonpath([full, out]) != out or os.path.islink(full) or not os.path.isfile(full):
        return None
    return full


def read_job(key: str) -> dict | None:
    """The record of `key` while all its files exist; a record whose files went is deleted, and None comes back."""
    path = job_path(key)
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    outputs = rec.get("outputs") if isinstance(rec, dict) else None
    if not isinstance(outputs, dict) or not all(output_file(f) for f in record_files(outputs)):
        with contextlib.suppress(OSError):
            os.remove(path)
        return None
    return rec


def write_job(key: str, outputs, workflow: str = "") -> None:
    """Record what a job made. Only files in the output folder: a preview in temp is gone after a restart."""
    path = job_path(key)
    if not isinstance(outputs, dict) or not outputs:
        raise ValueError("A job record needs outputs")
    if not all(output_file(f) for f in record_files(outputs)):
        raise ValueError("A job record names only files in the output folder")
    data = json.dumps({"workflow": str(workflow)[:64], "outputs": outputs})
    if len(data) > JOB_MAX:
        raise ValueError("Job record too large")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
    os.replace(tmp, path)


async def job_get(request: web.Request) -> web.Response:
    try:
        rec = await asyncio.to_thread(read_job, request.match_info["key"])
    except ValueError:
        return web.Response(status=400)
    return web.json_response(rec or {"outputs": None})  # a miss is normal: no 404, which browsers log as an error


async def job_post(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        await asyncio.to_thread(write_job, request.match_info["key"], body.get("outputs"), body.get("workflow", ""))
    except (ValueError, AttributeError) as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True})


def plate_stat(rel: str) -> dict:
    """The size and time of a plate under the input folder, or under output when it starts with output:. A folder of
    frames counts its plain files. A plate that changes on disk changes this, and with it every job index key."""
    if rel.startswith("output:"):
        out = os.path.abspath(folder_paths.get_output_directory())
        full = os.path.abspath(os.path.join(out, rel[len("output:"):]))
        if os.path.commonpath([full, out]) != out or full == out or os.path.islink(full) or not os.path.exists(full):
            raise FileNotFoundError("No plate at this path")
    else:
        full = input_path(rel)
    if os.path.isfile(full):
        st = os.stat(full)
        return {"files": 1, "size": st.st_size, "mtime": st.st_mtime_ns}
    sts = [os.stat(e.path) for e in os.scandir(full) if e.is_file(follow_symlinks=False)]
    return {"files": len(sts), "size": sum(s.st_size for s in sts), "mtime": max((s.st_mtime_ns for s in sts), default=0)}


async def stat(request: web.Request) -> web.Response:
    try:
        return web.json_response(await asyncio.to_thread(plate_stat, request.query.get("path", "")))
    except (FileNotFoundError, NotADirectoryError):
        return web.Response(status=404)


def setup(server) -> None:
    """Add the routes to ComfyUI's server (or to anything with an aiohttp RouteTableDef as `routes`)."""
    server.routes.get("/paintaplate/download")(download)
    server.routes.get("/paintaplate/plates")(plates)
    server.routes.get("/paintaplate/thumb")(thumb)
    server.routes.post("/paintaplate/blank")(blank)
    server.routes.get("/paintaplate/jobs/{key}")(job_get)
    server.routes.post("/paintaplate/jobs/{key}")(job_post)
    server.routes.get("/paintaplate/stat")(stat)
