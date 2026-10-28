"""The page's HTTP routes: the export download, the plate browser of the Open dialog, and the blank plate.

    GET /paintaplate/download?run=paintaplate/<plate>/v3&name=shot010_paintaplate_v3&parts=export,matte
    GET /paintaplate/plates                      the plates in input/plates, as JSON (see list_plates)
    GET /paintaplate/thumb?path=plates/boat.mp4  the first frame of one of them as a small JPEG, cached in temp
    POST /paintaplate/blank {width, height, fps, frames}  a black ProRes 4444 plate in input/paintaplate/blank, for a fluid shot

`parts` chooses what the zip holds (default: export,matte): export is the result in the plate's own
format, matte where the plate changed, review an H.264 MP4 of the result (the export's full-size movie,
else the preview composite), shot the whole frame as the model made it (the full-size pass first). Only run folders under output/paintaplate are read, and only plain files inside
them: a symbolic link is skipped. The zip functions are plain Python (tests/test_routes.py);
setup() adds the routes to ComfyUI's server. The plate browser reads only input/plates (never a link out of it),
and its thumbnails are plain functions too (list_plates, thumbnail).
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
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


def setup(server) -> None:
    """Add the routes to ComfyUI's server (or to anything with an aiohttp RouteTableDef as `routes`)."""
    server.routes.get("/paintaplate/download")(download)
    server.routes.get("/paintaplate/plates")(plates)
    server.routes.get("/paintaplate/thumb")(thumb)
    server.routes.post("/paintaplate/blank")(blank)
