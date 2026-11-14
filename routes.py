"""The page's HTTP routes. Every path is a page path (folders.py): under the input folder, or the output folder with output:.
    GET  /paintaplate/browse?path=output:video        a folder for the Open dialog: subfolders, videos, sequences, scenes;
                                                      at a root, also the newest plates of the folders below it
    GET  /paintaplate/version                         the pack's version, from pyproject.toml: the page's top bar and log;
                                                      and its build, a hash of what computes (build_parts): job index keys
    GET  /paintaplate/thumb?path=output:a.mp4         the first frame of a plate as a small JPEG, made once, kept in temp
    GET  /paintaplate/stat?path=plates/boat.mp4&config=ocio://studio-config-latest
                                                      a plate's size and time (job index keys change with them), its spec
                                                      and its guessed file colour space in that OCIO config
    GET  /paintaplate/frames?path=...&first=0&count=4&side=960   frames of an image sequence or a video as RGB half floats
    GET  /paintaplate/pixel?path=...&frame=0&x=0&y=0&size=1      one pixel at full precision and native size (colour inspector)
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
import functools
import glob
import hashlib
import json
import logging
import os
import re
import time
import uuid
import zipfile

import folder_paths
from aiohttp import web
import av
import numpy as np

try:
    from . import folders, mathops, ocio, plateio
except ImportError:  # imported as a plain module by the tests, outside the package
    import folders, mathops, ocio, plateio

BLANK = "paintaplate/blank"  # the folder under the input folder that holds the black canvases of fluid shots
FOUND_MAX = 60  # plates the Open dialog lists at a root from the folders below it, newest first
FOUND_FOLDERS = 400  # folders read at most for them, breadth first: a root of thousands of folders still answers at once
# Paint a plate's own folders stay out of a root's plates: renders and the job index, uploaded masks, blank canvases
FOUND_SKIP = {"output:paintaplate", "paintaplate/up", "paintaplate/blank", "paintaplate/warm"}


def pack_version(folder: str | None = None) -> str:
    """A pack's version, from its pyproject.toml: this pack's (the Registry package keeps it), or the pack in `folder`."""
    try:
        with open(os.path.join(folder or os.path.dirname(os.path.abspath(__file__)), "pyproject.toml"), encoding="utf-8") as f:
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
                  "regenerated_shot.mp4"),
         # a fluid shot exported by itself: its HDR frames, the shot in the blank plate's format, its preview movie
         "hdr": (["hdr"], None), "plate": (["plate"], None), "preview": (["preview_*.mp4"], "preview.mp4")}
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


MODELS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "models.json")


def models_md(ids: list[str]) -> str:
    """MODELS.md for an export's zip: the models behind the result, which the page names (models.modelsBehind), each with
    its licence and source as web/models.json states them, in the registry's order. Unknown ids are left out."""
    with open(MODELS_JSON) as f:
        reg = json.load(f)
    rows = [m for m in reg["models"] if m["id"] in set(ids)]
    out = ["# Models behind this export", "", f"Made with AInVFX Paint a plate. Each model keeps its own licence, as its Hugging Face "
           f"repository states it at the pinned revision (read {reg.get('checked', '')}).", "",
           "| Model | File | What it did | Licence | Source |", "| --- | --- | --- | --- | --- |"]
    for m in rows:
        out.append(f"| {m['name']} | `{m['file']}` at `{m.get('revision', '')[:7]}` | {m.get('use', '')} | [{m.get('licence', '')}]({m.get('licence_url', '')}) | {m.get('source', '')} |")
    return "\n".join(out) + "\n"


# ---------- The build: what computes, in every job index key ----------
# The page puts it in every key in place of the pack's version (comfy.indexParts). A branch or a local edit of one version,
# an update of ComfyUI or of ComfyUI-LTXVideo, and a new model file under an old name each make new keys, so a result made by
# other code or other weights is never taken back. It is made once, when ComfyUI starts: the code that runs is the code
# ComfyUI imported then, whatever changes on disk later.
PACK = os.path.dirname(os.path.abspath(__file__))


def python_digest(folder: str, deep: bool = False) -> str:
    """SHA-256 of a folder's Python files, by name and content: its top level, or its subfolders too with `deep`."""
    digest = hashlib.sha256()
    for top, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if deep and not d.startswith(".") and d != "__pycache__")
        for name in sorted(n for n in names if n.endswith(".py")):
            path = os.path.join(top, name)
            with open(path, "rb") as f:
                digest.update(f"{os.path.relpath(path, folder)}\0".encode() + f.read() + b"\0")
    return digest.hexdigest()


def git_commit(folder: str) -> str:
    """The commit a git clone is on, read from its .git folder with no git command; "" for a folder that is not a clone."""
    git = os.path.join(folder, ".git")
    try:
        if os.path.isfile(git):  # a submodule or a worktree: "gitdir: <path>"
            with open(git, encoding="utf-8") as f:
                git = os.path.join(folder, f.read().split(":", 1)[1].strip())
        with open(os.path.join(git, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
        if not head.startswith("ref: "):
            return head  # a detached HEAD holds the commit itself
        ref = head[5:]
        if os.path.isfile(os.path.join(git, ref)):
            with open(os.path.join(git, ref), encoding="utf-8") as f:
                return f.read().strip()
        with open(os.path.join(git, "packed-refs"), encoding="utf-8") as f:
            return next((line.split()[0] for line in f if line.rstrip().endswith(f" {ref}")), "")
    except (OSError, IndexError):
        return ""


def comfy_version(root: str) -> str:
    """ComfyUI's version, from comfyui_version.py at its root; "" when there is none."""
    try:
        with open(os.path.join(root, "comfyui_version.py"), encoding="utf-8") as f:
            m = re.search(r"""__version__\s*=\s*["']([^"']+)""", f.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def ltx_folder() -> str:
    """ComfyUI-LTXVideo's folder among the custom nodes; "" when it is not there (the page then stops on its nodes)."""
    roots = getattr(folder_paths, "get_folder_paths", lambda _: [])("custom_nodes") or [os.path.dirname(PACK)]
    for root in roots:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            if name.lower().startswith("comfyui-ltxvideo") and not name.endswith(".disabled") and os.path.isdir(os.path.join(root, name)):
                return os.path.join(root, name)
    return ""


def model_path(name: str) -> str | None:
    """Where this ComfyUI keeps a model file, in any of its model folders (extra_model_paths.yaml's too); None: nowhere."""
    for kind in list(getattr(folder_paths, "folder_names_and_paths", {})):
        try:
            path = folder_paths.get_full_path(kind, name)
        except Exception:  # a folder kind that holds no such file
            path = None
        if path:
            return path
    return None


def model_stats(names: list[str], find=model_path) -> list:
    """Each model file as [name, size, time], or [name] when this ComfyUI has none."""
    stats = []
    for name in names:
        try:
            st = os.stat(find(name) or "")
            stats.append([name, st.st_size, int(st.st_mtime)])
        except OSError:
            stats.append([name])
    return stats


def build_parts(pack: str = PACK, root: str | None = None, ltx: str | None = None, models: list | None = None) -> dict:
    """What computes: the pack's Python files (its top level, the modules ComfyUI imports), ComfyUI's version and commit,
    ComfyUI-LTXVideo's commit (the hash of its Python files when it is not a git clone), and the name, size and time of
    each model file of web/models.json. pyproject.toml is not in it: a new version number alone changes nothing."""
    if root is None:
        root = os.path.dirname(os.path.abspath(folder_paths.__file__)) if getattr(folder_paths, "__file__", None) else ""
    ltx = ltx_folder() if ltx is None else ltx
    if models is None:
        with open(MODELS_JSON, encoding="utf-8") as f:
            models = model_stats([m["file"] for m in json.load(f)["models"]])
    return {"pack": python_digest(pack), "comfyui": [comfy_version(root), git_commit(root)] if root else [],
            "ltx": (git_commit(ltx) or python_digest(ltx, deep=True)) if ltx else "", "models": models}


def ltx_label(ltx: str, value: str) -> str:
    """ComfyUI-LTXVideo as the build line names it: its commit when the folder is a git clone; otherwise its version, from
    its pyproject.toml, and the hash of its Python files, said as such. That hash reads like a commit: on the laptop it was
    taken for one and compared with the pin (13 Nov 2026). `value`: build_parts' « ltx », which the key keeps as it is."""
    if not value:
        return "not found"
    if git_commit(ltx):
        return value[:7]
    version = pack_version(ltx) or ""
    return (f"{version}, " if version[:1].isdigit() else "") + f"files {value[:7]} (not a git clone)"


def build_hash(parts: dict) -> str:
    """The build: 16 hex digits of the SHA-256 of build_parts."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


_built = build_parts()
BUILD = build_hash(_built)
logging.info("Paint a plate %s: build %s, from ComfyUI %s, ComfyUI-LTXVideo %s and %d of %d model files (the job index keys)",
             VERSION, BUILD, " ".join(x[:7] for x in _built["comfyui"] if x) or "unknown", ltx_label(ltx_folder(), _built["ltx"]),
             sum(len(m) == 3 for m in _built["models"]), len(_built["models"]))


def build_zip(folder: str, name: str, parts: list[str], models: list[str] | None = None) -> str:
    """The zip of `parts`, stored (EXR, PNG and video are already compressed) and reused while it is current, with
    MODELS.md when the page names the models behind the result."""
    files = collect(folder, parts)
    if "export" in parts and not any(arc.startswith("export/") for _, arc in files):
        raise FileNotFoundError("Export not found for this run. Run Export first.")
    if not files:  # a fluid shot's zip holds no export: its HDR frames, its plate and its preview
        raise FileNotFoundError("Download: no files in this run.")
    mark = f"__m{hashlib.sha1(','.join(models).encode()).hexdigest()[:8]}" if models else ""  # another list of models, another zip
    target = os.path.join(folder, f"{name}__{'-'.join(p for p in PARTS if p in parts)}{mark}.zip")
    newest = max(os.path.getmtime(p) for p, _ in files)
    if os.path.exists(target) and os.path.getmtime(target) >= newest:
        return target
    part = f"{target}.{uuid.uuid4().hex}.part"  # two downloads at once never write the same file
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for path, arc in sorted(files, key=lambda f: f[1]):
                z.write(path, arc)
            if models:
                z.writestr("MODELS.md", models_md(models))
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
        models = [m for m in request.query.get("models", "").split(",") if m]
        path = await asyncio.to_thread(build_zip, folder, name, asked, models)
    except FileNotFoundError as exc:
        raise web.HTTPNotFound(text=str(exc)) from exc
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


# ---------- The plate browser ----------

def browse(rel: str) -> dict:
    """A folder of the input or output folder, as the Open dialog lists it, with no file opened (plateio.scan_folder).
    Each item carries the page path that opens it: a frame pattern for a sequence, the file for a video or a scene."""
    full = folders.plate_path(rel, folder=True)
    if not os.path.isdir(full):
        raise FileNotFoundError(f"Folder not found: {rel}.")
    page = folders.page_path(full)
    listed = plateio.scan_folder(full)
    for item in listed["items"]:
        item["path"] = f"{page}/{item['name']}" if page not in ("", folders.OUTPUT) else page + item["name"]
    parent = None if page in ("", folders.OUTPUT) else (page.rsplit("/", 1)[0] if "/" in page else
                                                        (folders.OUTPUT if page.startswith(folders.OUTPUT) else ""))
    return {"path": page, "parent": parent, **listed, "found": plates_below(full, page) if parent is None else []}


def plates_below(full: str, page: str) -> list:
    """At a root, the newest plates of the folders below it, so the Open dialog shows plates at once: FOUND_MAX of them,
    from at most FOUND_FOLDERS folders read breadth first, Paint a plate's own folders left out (FOUND_SKIP). Each carries
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


def first_frame(first: str, still: bool) -> np.ndarray:
    """The first frame of a plate as float RGB: `first` is an image sequence's first file (`still`), or a video or an
    animated image. Float formats keep their values (plateio.read_float); 8-bit ones come back from 0 to 1."""
    if still:
        return plateio.read_float(first)
    with plateio.av.open(first) as c:
        return next(c.decode(video=0)).to_ndarray(format="rgb48le").astype(np.float32) / 65535.0


def thumbnail(rel: str, width: int = THUMB_WIDTH) -> str:
    """A JPEG of a plate's first frame, `width` wide, as the viewer shows it at its defaults (ocio.display_rgb from the
    guessed file colour space), written once to temp/paintaplate_thumbs and reused while the plate is unchanged."""
    from PIL import Image

    full = folders.plate_path(rel)
    still = plateio.is_sequence(full)
    first = plateio.find_sequence(full)[0] if still else full  # the folder is listed once
    folder = os.path.join(folder_paths.get_temp_directory(), "paintaplate_thumbs")
    os.makedirs(folder, exist_ok=True)
    key = hashlib.sha1(f"{full}|{os.path.getmtime(first)}|{width}".encode()).hexdigest()[:20]
    target = os.path.join(folder, f"{key}.jpg")
    if os.path.exists(target):
        return target
    rgb = first_frame(first, still)
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
    return web.json_response({"version": VERSION, "build": BUILD})


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
        raise ValueError("Blank plate: width and height must be multiples of 64, from 64 to 4096 px.")
    if not (9 <= frames <= 1025 and (frames - 1) % 8 == 0):
        raise ValueError("Blank plate: length must be 8k + 1 frames, from 9 to 1,025.")
    if not 1 <= fps <= 120:
        raise ValueError("Blank plate: frame rate must be from 1 to 120 fps.")
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
        raise web.HTTPBadRequest(text=str(exc) if str(exc).startswith("Blank plate:") else f"Blank plate: request not valid ({exc}).") from exc
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


def headroom(config: str, cs: str) -> float:
    """The scene-linear value that code value 1.0 decodes to in colour space `cs`: 1.0 for sRGB, a display or a linear
    space; above 1.0 for a log encoding (in the studio config, 2 Nov: ACEScct 222.9, ARRI LogC4 469.8, ADX16 65504), so
    an integer plate in such a space still holds the values above 1.0 that SDR to HDR makes. 1.0 when it cannot be read."""
    try:
        return round(float(np.max(ocio.convert([np.ones((1, 1, 3), np.float32)], config, cs, "@linear")[0])), 3)
    except Exception:
        return 1.0


def plate_info(rel: str, config: str = "", cs: str = "") -> dict:
    """What the Open dialog says about a plate, its file colour space guessed in `config`, for the viewer's OCIO, and the
    headroom of `cs` (else of that guess)."""
    full = folders.plate_path(rel)
    spec = plateio.probe_plate(full)
    first = spec["files"][0] if spec.get("files") else full
    keep = ("kind", "ext", "codec", "pix_fmt", "width", "height", "frames", "fps", "first_frame", "missing")
    guess = ocio.guess(config, plateio.guess_color_space(spec), first)
    return {**plate_stat(rel), **{k: spec[k] for k in keep if k in spec}, "color_space": guess, "headroom": headroom(config, cs or guess)}


async def stat(request: web.Request) -> web.Response:
    try:
        return web.json_response(await asyncio.to_thread(plate_info, request.query.get("path", ""), request.query.get("config", ""),
                                                         request.query.get("cs", "")))
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=404)


DEEP_FRAMES_MAX = 16  # frames per request
STILLS = (".exr", ".png", ".tif", ".tiff", ".dpx")


# YUV to RGB weights (Kr, Kb) by the file's colorspace tag, as ITU-T H.273 numbers them: BT.709, BT.601 (470BG and
# SMPTE 170M), BT.2020. An untagged file takes BT.709 from 720 rows up, else BT.601, the usual players' rule.
YUV_WEIGHTS = {1: (0.2126, 0.0722), 5: (0.299, 0.114), 6: (0.299, 0.114), 9: (0.2627, 0.0593), 10: (0.2627, 0.0593)}
PLANAR_YUV = re.compile(r"^yuva?4(20|22|44)p(\d+)?(le)?$")


def _video_rgb(frame) -> np.ndarray:
    """A decoded video frame as float32 RGB, in its own values (0 to 1, or beyond for out-of-range codes). Planar YUV goes
    through the file's own matrix and range in float, from its samples at their bit depth, as OpenRV converts a source's
    YUV in its shader; swscale's 16-bit output was 0.77 of an 8-bit level off on a BT.709 red (2 Nov). Chroma is repeated
    over the pixels it covers. Other formats (RGB, NV12) go through swscale at 16 bits."""
    m = PLANAR_YUV.match(frame.format.name)
    if not m:
        return frame.to_ndarray(format="rgb48le").astype(np.float32) / 65535.0
    bits = int(m.group(2) or 8)
    dtype = np.uint16 if bits > 8 else np.uint8
    h, w = frame.height, frame.width
    planes = []
    for p in frame.planes[:3]:
        a = np.frombuffer(p, dtype)
        ph = a.size // (p.line_size // a.itemsize)
        a = a.reshape(ph, -1)[:, : p.width].astype(np.float32)
        planes.append(np.repeat(np.repeat(a, h // ph, 0), w // a.shape[1], 1)[:h, :w])
    y, cb, cr = planes
    k = float(1 << (bits - 8))
    if (frame.color_range or 1) == 2:  # full (JPEG) range
        top = float((1 << bits) - 1)
        y, cb, cr = y / top, (cb - 128 * k) / top, (cr - 128 * k) / top
    else:  # limited (MPEG) range, the default
        y, cb, cr = (y - 16 * k) / (219 * k), (cb - 128 * k) / (224 * k), (cr - 128 * k) / (224 * k)
    kr, kb = YUV_WEIGHTS.get(frame.colorspace, YUV_WEIGHTS[1] if h >= 720 else YUV_WEIGHTS[5])
    kg = 1 - kr - kb
    r = y + 2 * (1 - kr) * cr
    b = y + 2 * (1 - kb) * cb
    g = (y - kr * r - kb * b) / kg
    return np.stack([r, g, b], -1)


def video_frames(path: str, first: int, count: int) -> list[np.ndarray]:
    """Frames `first` to `first + count - 1` of a video at native size: a seek to the key frame before, then a decode up
    to them. A frame past the end holds the last, as Load Plate pads a shot."""
    out, last = [], None
    with av.open(path) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        rate, tb, start = s.average_rate or s.guessed_rate, s.time_base, s.start_time or 0
        if first and rate and tb:
            c.seek(start + int(first / rate / tb), stream=s, backward=True)
        n = None
        for f in c.decode(s):
            n = round(float((f.pts - start) * tb * rate)) if f.pts is not None and rate and tb else (0 if n is None else n + 1)
            last = f
            if n >= first:
                out.append(_video_rgb(f))
                if len(out) == count:
                    break
        if last is None:
            raise ValueError("Plate has no frames. Check the file.")
    return out + [out[-1] if out else _video_rgb(last)] * (count - len(out))


def frame_rgb(full: str, index: int) -> np.ndarray:
    """One frame of a plate, a review or a pass at native size and full precision: an image sequence's or a still's own
    values (an EXR's half floats as stored), a video's decoded with its own YUV matrix and range."""
    if plateio.is_sequence(full):
        files = plateio.sequence_frames(full)[0]
        if not files:
            raise ValueError("Plate has no frames. Check the file.")
        return plateio.read_float(files[min(max(0, index), len(files) - 1)])
    if full.lower().endswith(STILLS):
        return plateio.read_float(full)
    return video_frames(full, max(0, index), 1)[0]


def deep_frames(rel: str, first: int, count: int, side: int) -> tuple[bytes, int, int]:
    """Frames `first` to `first + count - 1` of an image sequence (a plate, or a render's review frames) or of a video
    plate, at most `side` px on the long side, as RGB half floats.

    The viewer's colour tools read these, as OpenRV's cache keeps an EXR's half floats: values above 1.0 and below 0
    stay as stored, and nothing passes through an 8-bit video. A video plate's frames are its source file's, decoded at
    full precision, for the frame on show while paused. A missing frame holds the one before (plateio), and a frame past
    the end holds the last, as Load Plate pads a shot.
    """
    full = folders.plate_path(rel)  # a plate, or a render's review frames
    first, count, side = max(0, first), min(max(1, count), DEEP_FRAMES_MAX), min(max(64, side), 4096)
    if plateio.is_sequence(full) or full.lower().endswith(STILLS):
        frames = [frame_rgb(full, i) for i in range(first, first + count)]
    else:
        frames = video_frames(full, first, count)
    out = []
    for rgb in frames:
        h, w = rgb.shape[:2]
        k = min(1.0, side / max(h, w))
        out.append(mathops.resize_to(rgb, max(1, round(h * k)), max(1, round(w * k))) if k < 1.0 else rgb)
    data = np.nan_to_num(np.stack(out), nan=0.0, posinf=65504.0, neginf=-65504.0).clip(-65504.0, 65504.0).astype("<f2")
    return data.tobytes(), data.shape[2], data.shape[1]


@functools.lru_cache(maxsize=2)  # the inspector reads many pixels of the frame on show
def _frame_cached(full: str, index: int, mtime: float) -> np.ndarray:
    return frame_rgb(full, index)


def pixel(rel: str, frame: int, x: int, y: int, size: int = 1, of: str = "") -> dict:
    """The colour inspector's read: the pixel at (x, y) of a frame, at native size, in the file's own values (an EXR's
    half floats as stored, above 1.0 and below 0), and the mean of the `size` x `size` pixels around it.

    `of` is the size of the grid (x, y) is in, as "3840x2160": the plate's. A frame of another size, such as a preview
    pass, is read at the same place of the picture in its own pixels, which the reply names (1.7.0 read the plate's
    pixel numbers in a 640 x 352 preview and failed)."""
    full = folders.plate_path(rel)
    stamp = os.path.getmtime(full if os.path.exists(full) else os.path.dirname(full))
    rgb = _frame_cached(full, max(0, frame), stamp)
    h, w = rgb.shape[:2]
    if of:
        ow, oh = (int(v) for v in of.lower().split("x"))
        if ow > 0 and oh > 0 and (ow, oh) != (w, h):
            x, y = int((x + 0.5) * w / ow), int((y + 0.5) * h / oh)
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(f"Pixel {x}, {y} outside the frame ({w} x {h}).")
    r = max(1, min(int(size), 64)) // 2
    block = rgb[max(0, y - r): y + r + 1, max(0, x - r): x + r + 1].reshape(-1, 3)
    out = {"width": w, "height": h, "x": x, "y": y, "frame": frame, "value": [float(v) for v in rgb[y, x]],
           "mean": [float(v) for v in block.mean(0)], "size": 2 * r + 1}
    if not (plateio.is_sequence(full) or full.lower().endswith(STILLS)):  # a movie: say what its samples are
        out["movie"] = _movie_info(full, stamp)
    return out


@functools.lru_cache(maxsize=16)
def _movie_info(full: str, mtime: float) -> dict:
    with av.open(full) as c:
        s = c.streams.video[0]
        name = s.codec_context.format.name if s.codec_context.format else ""
        m = re.search(r"p(\d+)(le|be)?$", name)
        return {"codec": s.codec_context.name, "pix_fmt": name, "bits": int(m.group(1)) if m and int(m.group(1)) > 8 else 8}


async def pixel_route(request):
    q = request.rel_url.query
    try:
        out = await asyncio.to_thread(pixel, q.get("path", ""), int(q.get("frame", 0)), int(q.get("x", 0)), int(q.get("y", 0)),
                                      int(q.get("size", 1)), q.get("of", ""))
    except (FileNotFoundError, ValueError) as e:
        return web.json_response({"error": str(e)}, status=404, headers={"Cache-Control": "no-store"})
    return web.json_response(out, headers={"Cache-Control": "no-store"})


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
        raise ValueError("Scene name not allowed. Use letters, digits, '.', '-' and '_'.")
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
        raise ValueError(f"Scene not saved: larger than {SCENE_MAX >> 20} MB.")
    scene = json.loads(body)
    if not isinstance(scene, dict) or scene.get("format") != "paintaplate-scene":
        raise ValueError("Scene not saved: not a Paint a plate scene.")
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


# ---------- A trace of every request, for the day ComfyUI's memory grows and no job runs ----------

TRACE = os.environ.get("PAINTAPLATE_TRACE") == "1"
TRACE_QUIET = (".js", ".mjs", ".css", ".map", ".svg", ".png", ".ico", ".woff", ".woff2", ".ttf", ".html", ".json")  # the front ends' own files


def held() -> float:
    """What this process holds now, in GB (VmRSS): 0.0 where /proc is not there."""
    try:
        with open("/proc/self/status") as f:
            return next(int(line.split()[1]) for line in f if line.startswith("VmRSS")) / 2**20
    except (OSError, StopIteration, ValueError):
        return 0.0


@web.middleware
async def trace(request: web.Request, handler):
    """One line in ComfyUI's log when a request starts and one when it ends: its method and address, the seconds, and the
    memory the process holds. Every request to ComfyUI passes here, the pack's routes and the others. A request that
    starts and never ends is one that ran when ComfyUI stopped. A front end's own file is said only when it is slow or
    heavy. On with PAINTAPLATE_TRACE=1 in ComfyUI's environment (11 Nov: ComfyUI reached a 40 GB cap with the page open
    and no job posted, and nothing in its log said which request had run)."""
    what, t0, before = f"{request.method} {request.path_qs[:240]}", time.perf_counter(), held()
    quiet = request.method == "GET" and request.path.endswith(TRACE_QUIET) and not request.path.startswith("/paintaplate/")
    if not quiet:
        logging.info("[Paint a plate] Trace: %s started, RAM %.1f GB.", what, before)
    try:
        return await handler(request)
    finally:
        seconds, after = time.perf_counter() - t0, held()
        if not quiet or seconds >= 0.5 or after - before >= 0.1:
            logging.info("[Paint a plate] Trace: %s ended, done in %.2f s, RAM %.1f GB.", what, seconds, after)


async def _pulse(app) -> None:
    """With the trace on: one line each time the memory has moved by half a GB, so growth between two requests shows."""
    async def watch():
        last = held()
        while True:
            await asyncio.sleep(1)
            now = held()
            if abs(now - last) >= 0.5:
                logging.info("[Paint a plate] Trace: process RAM %.1f GB.", now)
                last = now
    app["paintaplate_pulse"] = asyncio.create_task(watch())


def setup(server) -> None:
    """Add the routes to ComfyUI's server (or to anything with an aiohttp RouteTableDef as `routes`)."""
    app = getattr(server, "app", None)
    if TRACE and app is not None:
        app.middlewares.append(trace)
        app.on_startup.append(_pulse)
        logging.info("[Paint a plate] Trace: on.\n  One line per request to ComfyUI, at its start and at its end.")
    server.routes.get("/paintaplate/download")(download)
    server.routes.get("/paintaplate/browse")(browse_route)
    server.routes.get("/paintaplate/thumb")(thumb)
    server.routes.post("/paintaplate/blank")(blank)
    server.routes.get("/paintaplate/jobs/{key}")(job_get)
    server.routes.post("/paintaplate/jobs/{key}")(job_post)
    server.routes.get("/paintaplate/stat")(stat)
    server.routes.get("/paintaplate/frames")(frames)
    server.routes.get("/paintaplate/pixel")(pixel_route)
    server.routes.get("/paintaplate/scenes")(scenes)
    server.routes.get("/paintaplate/scenes/{name}")(scene_get)
    server.routes.post("/paintaplate/scenes/{name}")(scene_post)
    server.routes.get("/paintaplate/ocio")(ocio_route)
    server.routes.get("/paintaplate/ocio/shader")(ocio_shader)
    server.routes.get("/paintaplate/version")(version_route)
