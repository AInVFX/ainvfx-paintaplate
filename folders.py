"""Where Paint a plate reads and writes: every path the page sends resolves under ComfyUI's input or output folder.

A path that starts with "output:" names something in the output folder; any other path names something in the input
folder. A frame pattern (shot.####.exr, ComfyUI_#####_.png) names one image sequence in a folder. A symbolic link, or a
path that leaves its folder, is refused. Absolute paths need PAINTAPLATE_ALLOW_ABSOLUTE=1, which suits a workstation and
keeps a shared server's disk private. nodes.py and routes.py both resolve through here.
"""
from __future__ import annotations

import os

import folder_paths

try:
    from . import plateio
except ImportError:  # imported as a plain module by the tests, outside the package
    import plateio

OUTPUT = "output:"


def base(rel: str) -> str:
    """The ComfyUI folder a page path belongs to."""
    return os.path.abspath(folder_paths.get_output_directory() if rel.startswith(OUTPUT) else folder_paths.get_input_directory())


def plate_path(rel: str, folder: bool = False) -> str:
    """The file, folder or frame pattern `rel` names. ValueError when it is refused, FileNotFoundError when it is missing.
    `folder`: `rel` may name the root folder itself (the plate browser lists it)."""
    rel = (rel or "").strip()
    root, inner = base(rel), rel.removeprefix(OUTPUT)
    if os.path.isabs(inner):
        if os.environ.get("PAINTAPLATE_ALLOW_ABSOLUTE") != "1":
            raise ValueError("Absolute plate paths need PAINTAPLATE_ALLOW_ABSOLUTE=1")
        full = os.path.abspath(inner)
    else:
        full = os.path.abspath(os.path.join(root, inner))
        if os.path.commonpath([full, root]) != root or (full == root and not folder):
            raise ValueError(f"This path leaves ComfyUI's folders: {rel}")
    pattern = plateio.split_pattern(full)
    on_disk = pattern[0] if pattern else full
    if full != root and os.path.islink(on_disk):
        raise ValueError(f"Symbolic links are not followed: {rel}")
    if not os.path.exists(on_disk):
        raise FileNotFoundError(f"Nothing at {rel}")
    return full


def page_path(full: str) -> str:
    """The page's name for a path under the input or output folder: the inverse of plate_path."""
    for prefix, root in ((OUTPUT, folder_paths.get_output_directory()), ("", folder_paths.get_input_directory())):
        root = os.path.abspath(root)
        if os.path.commonpath([os.path.abspath(full), root]) == root:
            rel = os.path.relpath(full, root)
            return prefix + ("" if rel == "." else rel.replace(os.sep, "/"))
    raise ValueError("Outside ComfyUI's folders")


def output_folder(prefix: str) -> str:
    """A folder under ComfyUI's output folder, never outside it (as core Save Image refuses too)."""
    root = os.path.abspath(folder_paths.get_output_directory())
    full = os.path.abspath(os.path.join(root, prefix))
    if os.path.commonpath([full, root]) != root:
        raise ValueError(f"Saving outside the output folder is not allowed: {prefix}")
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
        raise FileNotFoundError("No render at this path")
    return full
