"""The page's one HTTP route: download a finished export as a zip, for a ComfyUI running on another machine.

    GET /paintaplate/download?run=paintaplate/<plate>/v3&name=shot010_paintaplate_v3&parts=export,matte

`parts` chooses what the zip holds (default: export,matte): export is the result in the plate's own
format, matte where the plate changed, review the composite as an H.264 MP4, shot the whole frame as
the model made it. Only run folders under output/paintaplate are read, and only plain files inside
them: a symbolic link is skipped. The zip functions are plain Python (tests/test_routes.py);
setup() adds the route to ComfyUI's server.
"""
from __future__ import annotations

import asyncio
import glob
import os
import re
import uuid
import zipfile

import folder_paths
from aiohttp import web

# part: (paths in the run folder, the first match wins for a file; its name in the zip, None for a folder)
PARTS = {"export": (["export"], None), "matte": (["matte"], None), "review": (["comp_*.mp4"], "review.mp4"),
         "shot": (["full_*.mp4", "raw_*.mp4"], "regenerated_shot.mp4")}
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


def setup(server) -> None:
    """Add the route to ComfyUI's server (or to anything with an aiohttp RouteTableDef as `routes`)."""
    server.routes.get("/paintaplate/download")(download)
