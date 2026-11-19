"""Where Paint a plate reads and writes, and how a path the page sends resolves.

A path that starts with "output:" names something in the output folder; any other path names something in the input
folder. A frame pattern (shot.####.exr, ComfyUI_#####_.png) names one image sequence in a folder. A path that leaves its
folder is refused, and so is a path that names a symbolic link (for a frame pattern, its folder); a link in a folder
above it is followed. An absolute path names a place on the machine itself (machine_path): a movie, a frame of a
sequence (the whole sequence) or a folder, read only when it has a plate's extension. It opens only when ComfyUI answers
this machine alone (on_this_machine): on a server that listens on the network, a file goes through the page's upload.
nodes.py and routes.py both resolve through here.
"""
from __future__ import annotations

import ipaddress
import os
import re

import folder_paths

try:
    from . import plateio
except ImportError:  # imported as a plain module by the tests, outside the package
    import plateio

OUTPUT = "output:"
WINDOWS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")  # C:\plates, C:/plates, \\server\share
THIS_MACHINE_ONLY = "Full paths open only when ComfyUI runs on this machine. Upload the file instead."


def absolute(rel: str) -> bool:
    """`rel` names a place on the machine itself, outside ComfyUI's folders: an absolute path here, or one in Windows' form
    (C:\\plates\\shot.mov, C:/plates/shot.mov, \\\\server\\share\\shot.mov), which on another system names nothing."""
    return os.path.isabs(rel) or bool(WINDOWS.match(rel))


def listens() -> list:
    """The addresses ComfyUI listens on, its --listen (several, with commas). An empty list outside ComfyUI."""
    try:
        from comfy.cli_args import args  # ComfyUI's own arguments, read when a path asks
    except ImportError:
        return []
    return [a.strip() for a in str(args.listen).split(",") if a.strip()]


def on_this_machine() -> bool:
    """ComfyUI answers this machine alone: every address it listens on is a loopback one (127.0.0.1, its default, ::1 or
    localhost). Only then does an absolute path open. Load Plate reads its path inside a prompt, where no client's address
    exists, and any client that can post a prompt can name a path: only the listener limits those clients to this machine."""
    def loopback(address: str) -> bool:
        try:
            return address == "localhost" or ipaddress.ip_address(address).is_loopback
        except ValueError:
            return False
    heard = listens()
    return bool(heard) and all(loopback(a) for a in heard)


def machine_path(rel: str) -> str:
    """The movie, frame pattern or folder that the absolute path `rel` names; a frame of a numbered sequence names the
    whole sequence. FileNotFoundError when nothing is there, ValueError for a file that is not a plate, PermissionError
    when this process may not read it. Symbolic links are followed: the person named the place."""
    full = os.path.normpath(rel)
    pattern = plateio.split_pattern(full)
    on_disk = pattern[0] if pattern else full
    if not os.path.exists(on_disk):
        raise FileNotFoundError(f"No file or folder at {rel}.")
    if not os.access(on_disk, os.R_OK):
        raise PermissionError(f"ComfyUI cannot read {rel}: check its permissions.")
    if pattern or os.path.isdir(full):
        return full
    if os.path.splitext(full)[1].lower() not in plateio.IMAGE_EXTS | plateio.VIDEO_EXTS:
        raise ValueError(f"{os.path.basename(full)} is not a plate: open a movie, a frame of a sequence or a folder.")
    folder, name = os.path.split(full)
    for item in plateio.scan_folder(folder)["items"]:
        if item["kind"] == "sequence" and re.fullmatch(
                re.sub(r"#+", lambda m: rf"\d{{{len(m.group(0))}}}", re.escape(item["name"]).replace("\\#", "#")), name):
            return os.path.join(folder, item["name"])
    return full


def base(rel: str) -> str:
    """The ComfyUI folder a page path belongs to."""
    return os.path.abspath(folder_paths.get_output_directory() if rel.startswith(OUTPUT) else folder_paths.get_input_directory())


def plate_path(rel: str, folder: bool = False) -> str:
    """The file, folder or frame pattern `rel` names. ValueError when it is refused, FileNotFoundError when it is missing.
    `folder`: `rel` may name the root folder itself (the plate browser lists it)."""
    rel = (rel or "").strip()
    if absolute(rel):
        if not on_this_machine():
            raise PermissionError(THIS_MACHINE_ONLY)
        return machine_path(rel)
    root, inner = base(rel), rel.removeprefix(OUTPUT)
    full = os.path.abspath(os.path.join(root, inner))
    if os.path.commonpath([full, root]) != root or (full == root and not folder):
        raise ValueError(f"This path leaves ComfyUI's folders: {rel}.")
    pattern = plateio.split_pattern(full)
    on_disk = pattern[0] if pattern else full
    if full != root and os.path.islink(on_disk):
        raise ValueError(f"Symbolic links are not followed: {rel}.")
    if not os.path.exists(on_disk):
        raise FileNotFoundError(f"Nothing at {rel}.")
    return full


def page_path(full: str) -> str:
    """The page's name for a path under the input or output folder: the inverse of plate_path."""
    for prefix, root in ((OUTPUT, folder_paths.get_output_directory()), ("", folder_paths.get_input_directory())):
        root = os.path.abspath(root)
        if os.path.commonpath([os.path.abspath(full), root]) == root:
            rel = os.path.relpath(full, root)
            return prefix + ("" if rel == "." else rel.replace(os.sep, "/"))
    raise ValueError("Outside ComfyUI's folders.")


def output_folder(prefix: str) -> str:
    """A folder under ComfyUI's output folder, never outside it (as core Save Image refuses too)."""
    root = os.path.abspath(folder_paths.get_output_directory())
    full = os.path.abspath(os.path.join(root, prefix))
    if os.path.commonpath([full, root]) != root:
        raise ValueError(f"Saving outside the output folder is not allowed: {prefix}.")
    return full


def run_folder(rel: str) -> str:
    """A render's folder under output/paintaplate. FileNotFoundError for any other path, and for a folder whose real path
    leaves output/paintaplate through a symbolic link. The output folder itself may be a link (to a bigger disk)."""
    out = os.path.abspath(folder_paths.get_output_directory())
    root = os.path.join(out, "paintaplate")
    full = os.path.abspath(os.path.join(out, rel.removeprefix(OUTPUT)))
    real_root, real = os.path.realpath(root), os.path.realpath(full)
    if (os.path.commonpath([full, root]) != root or full == root or not os.path.isdir(full)
            or os.path.commonpath([real, real_root]) != real_root or real == real_root):
        raise FileNotFoundError("No render at this path.")
    return full
