"""Download the example plates of Paint a plate into ComfyUI's input folder, where the Open plate dialog lists them.

    python get_plates.py [FOLDER] [--list] [--only FILE ...] [--revision REVISION]

Run it with the Python that runs ComfyUI, which has huggingface_hub. It works the same on Windows, macOS and Linux, on a
local machine and on a pod. Without FOLDER it uses input/plates of the ComfyUI this pack is installed in
(custom_nodes/ainvfx-paintaplate). The plates are the MP4 files of the Hugging Face dataset AInVFX/ainvfx-paintaplate:
synthetic shots under CC BY 4.0, about 150 MB in all, with no token to set. A plate already in place is skipped. --list
prints each plate with its size and whether it is in place, and downloads nothing. The last line says how many plates
were downloaded, were already there and are missing; the exit code is 1 while a plate is missing. get_models.py,
beside this file, downloads the models with the same code.
"""
from __future__ import annotations

import argparse
import os
import sys

from get_models import comfy_folder, download, hub, listing, why

REPO = "AInVFX/ainvfx-paintaplate"  # a Hugging Face dataset


def plates(revision: str) -> dict[str, int]:
    """The dataset's MP4 files at `revision`, each with its size in bytes."""
    return {f.path: f.size for f in hub().HfApi().list_repo_tree(REPO, repo_type="dataset", revision=revision) if f.path.endswith(".mp4")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Download the example plates of Paint a plate into ComfyUI's input folder.")
    inputs = comfy_folder("input")
    ap.add_argument("folder", nargs="?", default=inputs and os.path.join(inputs, "plates"),
                    help="the folder the plates go to (default: input/plates of the ComfyUI this pack is in)")
    ap.add_argument("--only", nargs="+", metavar="FILE", help="these plates only, for example horse.mp4")
    ap.add_argument("--revision", default="main", help="a branch or a commit of the dataset (default: main, the newest plates)")
    ap.add_argument("--list", action="store_true", help="print each plate with its size and whether it is in place, then stop")
    a = ap.parse_args(argv)
    if not a.folder:
        print("Name the folder for the plates: python get_plates.py path/to/ComfyUI/input/plates", file=sys.stderr)
        return 2
    try:
        sizes = plates(a.revision)
    except Exception as exc:  # no network, or a revision the dataset does not have
        print(f"The list of plates did not come from huggingface.co/datasets/{REPO}: {why(exc, f'https://huggingface.co/datasets/{REPO}')}", file=sys.stderr)
        return 1
    unknown = sorted(set(a.only or ()) - set(sizes))
    if unknown:
        print(f"The dataset has no plate named {', '.join(unknown)}: python get_plates.py --list names them all.", file=sys.stderr)
        return 2
    files = [(REPO, name, a.revision, name) for name in sorted(sizes) if not a.only or name in a.only]
    if a.list:
        missing = listing(files, a.folder, "example plates", sizes)
    else:
        os.makedirs(a.folder, exist_ok=True)
        missing = download(files, a.folder, "example plates", "dataset")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
