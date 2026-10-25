"""Where the tests find things. Optional levels read these environment variables:

COMFYUI_DIR      a ComfyUI folder with this pack and ComfyUI-LTXVideo in custom_nodes (live tests)
COMFYUI_PYTHON   the Python that runs it (default: this one)
LTXVIDEO_DIR     ComfyUI-LTXVideo source, for the static check (default: COMFYUI_DIR/custom_nodes/ComfyUI-LTXVideo)
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMFY = os.environ.get("COMFYUI_DIR", "")
PYTHON = os.environ.get("COMFYUI_PYTHON", sys.executable)
LTX = os.environ.get("LTXVIDEO_DIR", os.path.join(COMFY, "custom_nodes", "ComfyUI-LTXVideo") if COMFY else "")
