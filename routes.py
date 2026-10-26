"""The page's one HTTP route: download a finished export as a zip, for a ComfyUI running on another machine.

    GET /paintaplate/download?run=paintaplate/<plate>/v3&name=shot010_paintaplate_v3

`parts` chooses what the zip holds (default: export,matte): export is the result in the plate's own
format, matte where the plate changed, review the composite as an H.264 MP4, shot the whole frame as
the model made it. Only folders under output/paintaplate can be read.
"""
from __future__ import annotations

import asyncio
import glob
import os
import re
import zipfile

import folder_paths
from aiohttp import web
from server import PromptServer

# part: (paths in the run folder, first match wins for files; name in the zip for a single file)
PARTS = {"export": (["export"], None), "matte": (["matte"], None), "review": (["comp_*.mp4"], "review.mp4"),
         "shot": (["full_*.mp4", "raw_*.mp4"], "regenerated_shot.mp4")}


def run_folder(rel: str) -> str:
    out = os.path.abspath(folder_paths.get_output_directory())
    root = os.path.join(out, "paintaplate")
    full = os.path.abspath(os.path.join(out, rel))
    if os.path.commonpath([full, root]) != root or full == root or not os.path.isdir(full):
        raise web.HTTPNotFound(text="No export at this path")
    return full


def collect(folder: str, parts: list[str]) -> list[tuple[str, str]]:
    """(path on disk, name in the zip) for each part asked for, in a fixed order."""
    files = []
    for part in [p for p in PARTS if p in parts]:
        patterns, single = PARTS[part]
        if single is None:  # a folder, kept as a folder
            files += [(os.path.join(d, f), os.path.relpath(os.path.join(d, f), folder))
                      for d, _, names in os.walk(os.path.join(folder, patterns[0])) for f in sorted(names)]
            continue
        found = next((m for pat in patterns for m in sorted(glob.glob(os.path.join(folder, pat)))), None)
        if found:
            files.append((found, single))
    return files


def build_zip(folder: str, name: str, parts: list[str]) -> str:
    """Store the files once (EXR, PNG and video files are already compressed); reuse the zip while it is current."""
    files = collect(folder, parts)
    if not any(arc.startswith("export/") for _, arc in files):
        raise web.HTTPNotFound(text="This run has no export yet")
    target = os.path.join(folder, f"{name}__{'-'.join(p for p in PARTS if p in parts)}.zip")
    newest = max(os.path.getmtime(p) for p, _ in files)
    if not (os.path.exists(target) and os.path.getmtime(target) >= newest):
        with zipfile.ZipFile(target + ".part", "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for path, arc in sorted(files, key=lambda f: f[1]):
                z.write(path, arc)
        os.replace(target + ".part", target)
    return target


@PromptServer.instance.routes.get("/paintaplate/download")
async def download(request: web.Request) -> web.StreamResponse:
    folder = run_folder(request.query.get("run", ""))
    name = re.sub(r"[^\w.-]", "_", request.query.get("name") or os.path.basename(folder))[:120]
    parts = [p for p in request.query.get("parts", "export,matte").split(",") if p in PARTS] or ["export", "matte"]
    path = await asyncio.to_thread(build_zip, folder, name, parts)
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})
