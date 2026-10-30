"""The page's HTTP routes. Every path is a page path (folders.py): under the input folder, or the output folder with output:.
    GET  /paintaplate/browse?path=output:video        a folder for the Open dialog: subfolders, videos, sequences, scenes;
                                                      at a root, also the newest plates of the folders below it
    GET  /paintaplate/version                         the pack's version, from pyproject.toml: the page's top bar and log
    GET  /paintaplate/thumb?path=output:a.mp4         the first frame of a plate as a small JPEG, made once, kept in temp
    GET  /paintaplate/stat?path=plates/boat.mp4&config=ocio://studio-config-latest
                                                      a plate's size and time (job index keys change with them), its spec
                                                      and its guessed file colour space in that OCIO config
    GET  /paintaplate/frames?path=...&first=0&count=4&side=960   frames of an image sequence as RGB half floats
    POST /paintaplate/blank {width, height, fps, frames}         a black ProRes 4444 plate for a fluid shot
    GET  /paintaplate/jobs/<key>, POST /paintaplate/jobs/<key>   the job index: a finished job's outputs by the hash of its inputs
    GET  /paintaplate/scenes, GET|POST /paintaplate/scenes/<name>  scenes saved on this ComfyUI (output/paintaplate/scenes)
    GET  /paintaplate/ocio?config=...                  the OCIO config: colour spaces by family, displays and views, looks
    GET  /paintaplate/ocio/shader?config=&space=&display=&view=&look=   the viewer's GLSL and lookup tables for a source
    GET  /paintaplate/download?run=paintaplate/<plate>/v3&name=shot010_paintaplate_v3&parts=export,matte
`parts` chooses what the zip holds (default: export,matte): export is the result in the plate's own format, matte where
the plate changed, review the full-size review movie (else the preview composite), shot the whole frame as the model made
it (the full-size pass first). Only render folders under output/paintaplate are zipped, and only plain files inside them.
Everything here is plain functions (tests/test_routes.py); setup() adds the routes to ComfyUI's server.
"""
from __future__ import annotations

import asyncio
import contextlib
import glob
import hashlib
import json
import os
import re
import uuid
import zipfile

import folder_paths
from aiohttp import web
import numpy as np

try:
    from . import folders, mathops, ocio, plateio
except ImportError:  # imported as a plain module by the tests, outside the package
    import folders, mathops, ocio, plateio

BLANK = "paintaplate/blank"  # the folder under the input folder that holds the black canvases of fluid shots
FOUND_MAX = 60  # plates the Open dialog lists at a root from the folders below it, newest first
FOUND_FOLDERS = 400  # folders read at most for them, breadth first: a root of thousands of folders still answers at once
# PaintAPlate's own folders stay out of a root's plates: renders and the job index, uploaded masks, blank canvases
FOUND_SKIP = {"output:paintaplate", "paintaplate/up", "paintaplate/blank", "paintaplate/warm"}


def pack_version() -> str:
    """The pack's version, from the pyproject.toml beside this file (the Registry package keeps it)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyproject.toml"), encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else "unknown"
    except OSError:
        return "unknown"


VERSION = pack_version()
SCENES = "paintaplate/scenes"  # scenes saved on this ComfyUI, under the output folder
THUMB_WIDTH = 240
THUMBS_AT_ONCE = asyncio.Semaphore(4)  # a folder of thousands of outputs asks for its thumbnails as they scroll into view

# part: (paths in the run folder, the first match wins for a file; its name in the zip, None for a folder).
# The page keeps each preview size's composite and passes in a folder named after the size (640x352/), the
# full-size passes in full/, and the export's review movie at the top; the last patterns read older runs.
PARTS = {"export": (["export"], None), "matte": (["matte"], None),
         "review": (["review_*.mp4", "*/comp_*.mp4", "comp_*.mp4"], "review.mp4"),
         "shot": (["full/raw_*.mp4", "full/clean_*.mp4", "*/raw_*.mp4", "*/clean_*.mp4", "full_*.mp4", "raw_*.mp4"],
                  "regenerated_shot.mp4")}
DEFAULT_PARTS = ["export", "matte"]


def zip_name(name: str, folder: str) -> str:
    """A file name made only of letters, digits, '.', '-' and '_'."""
    return re.sub(r"[^\w.-]", "_", name or os.path.basename(folder))[:120]


def collect(folder: str, parts: list[str]) -> list[tuple[str, str]]:
    """(path on disk, name in the zip) for each part asked for, in a fixed order."""
    real = os.path.realpath(folder)  # compared as real paths: the output folder itself may be a symbolic link

    def inside(path):
        return not os.path.islink(path) and os.path.commonpath([os.path.realpath(path), real]) == real

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
        folder = folders.run_folder(request.query.get("run", ""))
        name = zip_name(request.query.get("name", ""), folder)
        path = await asyncio.to_thread(build_zip, folder, name, asked)
    except FileNotFoundError as exc:
        raise web.HTTPNotFound(text=str(exc)) from exc
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


# ---------- The plate browser ----------

def browse(rel: str) -> dict:
    """A folder of the input or output folder, as the Open dialog lists it, with no file opened (plateio.scan_folder).
    Each item carries the page path that opens it: a frame pattern for a sequence, the file for a video or a scene."""
    full = folders.plate_path(rel, folder=True)
    if not os.path.isdir(full):
        raise FileNotFoundError("Not a folder")
    page = folders.page_path(full)
    listed = plateio.scan_folder(full)
    for item in listed["items"]:
        item["path"] = f"{page}/{item['name']}" if page not in ("", folders.OUTPUT) else page + item["name"]
    parent = None if page in ("", folders.OUTPUT) else (page.rsplit("/", 1)[0] if "/" in page else
                                                        (folders.OUTPUT if page.startswith(folders.OUTPUT) else ""))
    return {"path": page, "parent": parent, **listed, "found": plates_below(full, page) if parent is None else []}


def plates_below(full: str, page: str) -> list:
    """At a root, the newest plates of the folders below it, so the Open dialog shows plates at once: FOUND_MAX of them,
    from at most FOUND_FOLDERS folders read breadth first, PaintAPlate's own folders left out (FOUND_SKIP). Each carries
    its page path and its folder's. Like scan_folder, it opens no file and follows no link."""
    found, queue, read = [], [(full, page)], 0
    while queue and read < FOUND_FOLDERS:
        folder, at = queue.pop(0)
        read += 1
        try:
            items = plateio.scan_folder(folder)["items"]
        except OSError:  # a folder this process may not read
            continue
        for item in items:
            path = at + item["name"] if at in ("", folders.OUTPUT) else f"{at}/{item['name']}"
            if item["kind"] == "folder":
                if path not in FOUND_SKIP:
                    queue.append((os.path.join(folder, item["name"]), path))
            elif folder != full and item["kind"] in ("video", "sequence"):  # the root's own plates are its items
                found.append({**item, "path": path, "folder": at})
    return sorted(found, key=lambda i: -i["mtime"])[:FOUND_MAX]


def first_frame(full: str) -> np.ndarray:
    """The first frame of a plate as float RGB: an image sequence's first file, a video's or an animated image's first
    frame. Float formats keep their values (plateio.read_float); 8-bit ones come back from 0 to 1."""
    if plateio.is_sequence(full):
        return plateio.read_float(plateio.find_sequence(full)[0])
    with plateio.av.open(full) as c:
        return next(c.decode(video=0)).to_ndarray(format="rgb48le").astype(np.float32) / 65535.0


def thumbnail(rel: str, width: int = THUMB_WIDTH) -> str:
    """A JPEG of a plate's first frame, `width` wide, as the viewer shows it at its defaults (ocio.display_rgb from the
    guessed file colour space), written once to temp/paintaplate_thumbs and reused while the plate is unchanged."""
    from PIL import Image

    full = folders.plate_path(rel)
    first = plateio.find_sequence(full)[0] if plateio.is_sequence(full) else full
    folder = os.path.join(folder_paths.get_temp_directory(), "paintaplate_thumbs")
    os.makedirs(folder, exist_ok=True)
    key = hashlib.sha1(f"{full}|{os.path.getmtime(first)}|{width}".encode()).hexdigest()[:20]
    target = os.path.join(folder, f"{key}.jpg")
    if os.path.exists(target):
        return target
    rgb = first_frame(full)
    h, w = rgb.shape[:2]
    k = min(1.0, width / max(h, w))
    small = mathops.resize_to(rgb, max(1, round(h * k)), max(1, round(w * k))) if k < 1.0 else rgb
    spec = {"ext": os.path.splitext(first)[1].lower(), "kind": "sequence" if plateio.is_sequence(full) else "video"}
    if spec["ext"] == ".exr":
        spec["exr"] = plateio.exr_info(first)
    shown = ocio.display_rgb(small, "", ocio.guess("", plateio.guess_color_space(spec), first))
    part = f"{target}.{uuid.uuid4().hex}.part"
    Image.fromarray((shown * 255.0 + 0.5).astype(np.uint8)).save(part, "JPEG", quality=80)
    os.replace(part, target)
    return target


async def version_route(request: web.Request) -> web.Response:
    return web.json_response({"version": VERSION})


async def browse_route(request: web.Request) -> web.Response:
    try:
        return web.json_response(await asyncio.to_thread(browse, request.query.get("path", "")))
    except (FileNotFoundError, ValueError, NotADirectoryError) as exc:
        return web.json_response({"error": str(exc)}, status=404)


async def thumb(request: web.Request) -> web.StreamResponse:
    try:
        async with THUMBS_AT_ONCE:
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
    return [f for o in outputs.values() if isinstance(o, dict) for k in ("images", "gifs", "video", "files") for f in (o.get(k) or [])]


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
    except (ValueError, AttributeError, TypeError) as e:  # a malformed record is refused, never a server error
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True})


def plate_stat(rel: str) -> dict:
    """The size and time of a plate: a job index key changes when the plate does. A sequence counts its frame files."""
    full = folders.plate_path(rel)
    if os.path.isfile(full):
        st = os.stat(full)
        return {"files": 1, "size": st.st_size, "mtime": st.st_mtime_ns}
    sts = [os.stat(f) for f in sorted(set(plateio.find_sequence(full)))]
    return {"files": len(sts), "size": sum(s.st_size for s in sts), "mtime": max((s.st_mtime_ns for s in sts), default=0)}


def plate_info(rel: str, config: str = "") -> dict:
    """What the Open dialog says about a plate, and its file colour space guessed in `config`, for the viewer's OCIO."""
    full = folders.plate_path(rel)
    spec = plateio.probe_plate(full)
    first = spec["files"][0] if spec.get("files") else full
    keep = ("kind", "ext", "codec", "pix_fmt", "width", "height", "frames", "fps", "first_frame", "missing")
    return {**plate_stat(rel), **{k: spec[k] for k in keep if k in spec},
            "color_space": ocio.guess(config, plateio.guess_color_space(spec), first)}


async def stat(request: web.Request) -> web.Response:
    try:
        return web.json_response(await asyncio.to_thread(plate_info, request.query.get("path", ""), request.query.get("config", "")))
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=404)


DEEP_FRAMES_MAX = 16  # frames per request
STILLS = (".exr", ".png", ".tif", ".tiff", ".dpx")


def deep_frames(rel: str, first: int, count: int, side: int) -> tuple[bytes, int, int]:
    """Frames `first` to `first + count - 1` of an image sequence (a plate, or a render's review frames), at most `side` px
    on the long side, as RGB half floats.

    The viewer's colour tools read these, as OpenRV's cache keeps an EXR's half floats: values above 1.0 and below 0
    stay as stored, and nothing passes through an 8-bit video. A missing frame holds the one before (plateio), and a
    frame past the end holds the last, as Load Plate pads a shot.
    """
    full = folders.plate_path(rel)  # a plate, or a render's review frames
    if plateio.is_sequence(full):
        files = plateio.sequence_frames(full)[0]
    elif full.lower().endswith(STILLS):
        files = [full]
    else:
        raise ValueError("A video plate: the viewer reads its playback video")
    if not files:
        raise ValueError("No frames in this plate")
    first, count, side = max(0, first), min(max(1, count), DEEP_FRAMES_MAX), min(max(64, side), 4096)
    out = []
    for i in range(first, first + count):
        rgb = plateio.read_float(files[min(i, len(files) - 1)])
        h, w = rgb.shape[:2]
        k = min(1.0, side / max(h, w))
        out.append(mathops.resize_to(rgb, max(1, round(h * k)), max(1, round(w * k))) if k < 1.0 else rgb)
    data = np.nan_to_num(np.stack(out), nan=0.0, posinf=65504.0, neginf=-65504.0).clip(-65504.0, 65504.0).astype("<f2")
    return data.tobytes(), data.shape[2], data.shape[1]


async def frames(request):
    q = request.rel_url.query
    try:
        body, w, h = await asyncio.to_thread(deep_frames, q.get("path", ""), int(q.get("first", 0)),
                                             int(q.get("count", 1)), int(q.get("side", 960)))
    except (FileNotFoundError, ValueError) as e:
        return web.Response(status=404, text=str(e))
    return web.Response(body=body, content_type="application/octet-stream",
                        headers={"X-Frame-Size": f"{w}x{h}", "Cache-Control": "no-store"})


# ---------- Scenes saved on this ComfyUI ----------

SCENE_NAME = re.compile(r"^[\w.-]{1,120}$")
SCENE_MAX = 64 << 20  # bytes: strokes are saved as drawn


def scene_path(name: str) -> str:
    if not SCENE_NAME.match(name or "") or name.startswith("."):
        raise ValueError("A scene name is letters, digits, '.', '-' and '_'")
    return os.path.join(folder_paths.get_output_directory(), SCENES, f"{name.removesuffix('.paintaplate.json')}.paintaplate.json")


def list_scenes() -> list[dict]:
    """Scenes saved here, newest first, with what the Open dialog shows: the plate's name and the number of edits."""
    folder = os.path.join(folder_paths.get_output_directory(), SCENES)
    out = []
    for e in sorted(os.scandir(folder), key=lambda e: -e.stat().st_mtime) if os.path.isdir(folder) else []:
        if not e.name.endswith(".paintaplate.json") or e.is_symlink():
            continue
        try:
            with open(e.path, encoding="utf-8") as fh:
                scene = json.load(fh)
        except (OSError, ValueError):
            continue
        out.append({"name": e.name.removesuffix(".paintaplate.json"), "mtime": e.stat().st_mtime,
                    "plate": os.path.basename(str((scene.get("plate") or {}).get("path", ""))), "edits": len(scene.get("edits") or [])})
    return out


def save_scene(name: str, body: bytes) -> None:
    if len(body) > SCENE_MAX:
        raise ValueError("Scene too large")
    scene = json.loads(body)
    if not isinstance(scene, dict) or scene.get("format") != "paintaplate-scene":
        raise ValueError("Not a PaintAPlate scene")
    path = scene_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(body)
    os.replace(tmp, path)


async def scenes(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(list_scenes))


async def scene_get(request: web.Request) -> web.StreamResponse:
    try:
        path = scene_path(request.match_info["name"])
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    if os.path.islink(path) or not os.path.isfile(path):  # a link is never followed, as list_scenes skips it
        raise web.HTTPNotFound(text="No scene by this name")
    return web.FileResponse(path, headers={"Cache-Control": "no-store"})


async def scene_post(request: web.Request) -> web.Response:
    try:
        await asyncio.to_thread(save_scene, request.match_info["name"], await request.read())
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    return web.json_response({"saved": request.match_info["name"]})


# ---------- OpenColorIO, for the viewer ----------

async def ocio_route(request: web.Request) -> web.Response:
    try:
        return web.json_response(await asyncio.to_thread(ocio.describe, request.query.get("config", "")))
    except Exception as exc:  # a broken $OCIO file names itself in the page, never a stack trace
        return web.json_response({"error": f"OCIO: {exc}"}, status=400)


async def ocio_shader(request: web.Request) -> web.Response:
    q = request.query
    try:
        out = await asyncio.to_thread(ocio.shader, q.get("config", ""), q.get("space", ""), q.get("display", ""),
                                      q.get("view", ""), q.get("look", ""))
    except Exception as exc:
        return web.json_response({"error": f"OCIO: {exc}"}, status=400)
    return web.json_response(out, headers={"Cache-Control": "no-store"})  # a new $OCIO or an updated pack shows at once


def setup(server) -> None:
    """Add the routes to ComfyUI's server (or to anything with an aiohttp RouteTableDef as `routes`)."""
    server.routes.get("/paintaplate/download")(download)
    server.routes.get("/paintaplate/browse")(browse_route)
    server.routes.get("/paintaplate/thumb")(thumb)
    server.routes.post("/paintaplate/blank")(blank)
    server.routes.get("/paintaplate/jobs/{key}")(job_get)
    server.routes.post("/paintaplate/jobs/{key}")(job_post)
    server.routes.get("/paintaplate/stat")(stat)
    server.routes.get("/paintaplate/frames")(frames)
    server.routes.get("/paintaplate/scenes")(scenes)
    server.routes.get("/paintaplate/scenes/{name}")(scene_get)
    server.routes.post("/paintaplate/scenes/{name}")(scene_post)
    server.routes.get("/paintaplate/ocio")(ocio_route)
    server.routes.get("/paintaplate/ocio/shader")(ocio_shader)
    server.routes.get("/paintaplate/version")(version_route)
