"""The page's one HTTP route: download a finished export as a zip, for a ComfyUI running on another machine.

    GET /paintaplate/download?run=paintaplate/<plate>/v3&name=shot010_paintaplate_v3

The zip holds the run's `export` folder (the plate's own format) and its `matte` folder (where the
plate changed). Only folders under output/paintaplate can be read.
"""
from __future__ import annotations

import asyncio
import os
import re
import zipfile

import folder_paths
from aiohttp import web
from server import PromptServer

PARTS = ("export", "matte")


def run_folder(rel: str) -> str:
    out = os.path.abspath(folder_paths.get_output_directory())
    root = os.path.join(out, "paintaplate")
    full = os.path.abspath(os.path.join(out, rel))
    if os.path.commonpath([full, root]) != root or full == root or not os.path.isdir(full):
        raise web.HTTPNotFound(text="No export at this path")
    return full


def build_zip(folder: str, name: str) -> str:
    """Store the files once (EXR, PNG and video files are already compressed); reuse the zip while it is current."""
    files = [(os.path.join(d, f), os.path.relpath(os.path.join(d, f), folder))
             for part in PARTS for d, _, names in os.walk(os.path.join(folder, part)) for f in sorted(names)]
    if not files:
        raise web.HTTPNotFound(text="This run has no export yet")
    target = os.path.join(folder, f"{name}.zip")
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
    path = await asyncio.to_thread(build_zip, folder, name)
    return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})
