"""Where the tests find things, and what happens when something they need is missing.

Optional levels read these environment variables:

COMFYUI_DIR      a ComfyUI folder with this pack and ComfyUI-LTXVideo in custom_nodes (live tests)
COMFYUI_PYTHON   the Python that runs it (default: this one)
LTXVIDEO_DIR     ComfyUI-LTXVideo source, for the static check (default: COMFYUI_DIR/custom_nodes/ComfyUI-LTXVideo)

A test package or tool that is missing skips its tests with what to install. In CI (GitHub Actions sets
CI=true) the same miss fails instead, so a broken install never passes as skipped.
"""
import importlib.util
import os
import shutil
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMFY = os.environ.get("COMFYUI_DIR", "")
PYTHON = os.environ.get("COMFYUI_PYTHON", sys.executable)
LTX = os.environ.get("LTXVIDEO_DIR", os.path.join(COMFY, "custom_nodes", "ComfyUI-LTXVideo") if COMFY else "")
CI = os.environ.get("CI", "").lower() == "true"
INSTALL = "pip install -r tests/requirements.txt"


def missing(hint: str):
    """Skip with what to install; in CI, fail."""
    if CI:
        raise RuntimeError(f"missing in CI: {hint}")
    raise unittest.SkipTest(hint)


def require(*packages: str) -> None:
    """Check the Python packages a test module or test needs (tests/requirements.txt) before importing them."""
    absent = [p for p in packages if importlib.util.find_spec(p) is None]
    if absent:
        missing(f"{INSTALL} (missing: {', '.join(absent)})")


def tool(name: str, hint: str) -> str:
    """The path of a command-line tool the tests run."""
    return shutil.which(name) or missing(hint)
