"""SDR to HDR's set as a compositor rebuilds it: the set's composite against its plate around its matte and its layer inside
it, comp = plate x (1 - matte) + layer x matte. Each frame comes from ComfyUI's output folder through /view, as the files a
person takes away; the flows read the set's folder from Export's line, which names the composite's frames."""
import io
import os
import re
import tempfile
import urllib.parse
import urllib.request

import numpy as np
import OpenEXR
from PIL import Image


def folder_of(lines):  # <run>/hdr: the set's folder, from Export's line that names the composite's EXR frames
    said = [m.group(1) for t in lines for m in [re.search(r"half-float EXR frames in ACES2065-1, in (\S+)/comp\.", t)] if m]
    return said[-1] if said else ""


def fetch(port, subfolder, filename):  # one file of ComfyUI's output folder
    query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": "output"})
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/view?{query}", timeout=30) as reply:
        return reply.read()


def exr(data):  # an EXR frame's RGB values
    with tempfile.NamedTemporaryFile(suffix=".exr", delete=False) as t:
        t.write(data)
    try:
        with OpenEXR.File(t.name) as f:
            ch = f.channels()
            rgb = ch["RGB"].pixels if "RGB" in ch else np.stack([ch[c].pixels for c in "RGB"], -1)
        return np.asarray(rgb, np.float32)
    finally:
        os.unlink(t.name)


def png16(data):  # a 16-bit grey matte frame, from 0 to 1
    a = np.asarray(Image.open(io.BytesIO(data)), np.float32)
    return (a[..., 0] if a.ndim == 3 else a)[..., None] / 65535


def rebuilt(port, folder, frames):
    """The largest difference between the set's composite and the one rebuilt from its plate, layer and matte, relative
    above 1.0 (half floats round by a share of the value), and the plate's and the layer's peak, on frames numbered from 1."""
    worst, peak = 0.0, 0.0
    for n in frames:
        plate, layer, comp = (exr(fetch(port, f"{folder}/{part}", f"f_{n:05d}_.exr")) for part in ("plate", "layer", "comp"))
        matte = png16(fetch(port, f"{folder}/matte", f"matte_{n:05d}_.png"))
        worst = max(worst, float(np.max(np.abs(comp - (plate * (1 - matte) + layer * matte)) / np.maximum(1.0, np.abs(comp)))))
        peak = max(peak, float(plate.max()), float(layer.max()))
    return worst, peak
