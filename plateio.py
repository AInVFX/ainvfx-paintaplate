"""Plate input and output helpers that core ComfyUI does not provide.

Core already decodes EXR, 16-bit PNG and video frames to float (Load Image and
Load Video go through PyAV) and writes single-layer EXR and PNG (Save Image
(Advanced)). This module fills the remaining gaps only:

* image sequences (a folder of numbered frames) and their spec,
* the source spec of a plate, so the export can match it,
* EXR export that keeps every untouched channel, layer, part and header
  attribute of the source frame (OpenEXR, optional),
* video export in the source codec, pixel format, colour tags and timecode,
  with the source audio copied.

Everything here is plain Python with numpy, PyAV and (optionally) OpenEXR, so
it runs and is tested outside ComfyUI.
"""
from __future__ import annotations

import json
import math
import os
import re
from fractions import Fraction

import numpy as np

from concurrent.futures import ThreadPoolExecutor

try:
    import av
    AVError = av.error.FFmpegError
except ImportError:  # ComfyUI always ships PyAV; tests may not
    av = None
    AVError = OSError

try:
    import OpenEXR  # BSD-3-Clause; needed only to keep extra EXR layers
except ImportError:
    OpenEXR = None

IMAGE_EXTS = {".exr", ".png", ".tif", ".tiff", ".dpx", ".jpg", ".jpeg", ".webp", ".avif"}
VIDEO_EXTS = {".mov", ".mp4", ".mkv", ".mxf", ".avi", ".webm", ".m4v"}
ANIMATIONS = {".gif", ".webp"}  # animated images, as core's Save Animated WEBP writes them: videos, never frames of a sequence
# The last number in a name is the frame: "shot.1001.exr", and also "f_00001_.png" as core Save Image writes.
_FRAME_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)(?P<suffix>[^\d]*?)(?P<ext>\.[A-Za-z0-9]+)$")
# One sequence of a folder, as RV and Nuke name it: shot.####.exr, ComfyUI_#####_.png or shot.%04d.exr
_PATTERN_RE = re.compile(r"^(?P<prefix>.*?)(?:#+|%0?\d*d)(?P<suffix>[^#%\d]*?)(?P<ext>\.[A-Za-z0-9]+)$")

# Encoder to use for each decoder name found in a source file.
_ENCODERS = {
    "prores": "prores_ks",
    "h264": "libx264",
    "hevc": "libx265",
    "dnxhd": "dnxhd",
    "mjpeg": "mjpeg",
    "ffv1": "ffv1",
    "av1": "libaom-av1",
    "vp9": "libvpx-vp9",
}
# Fallback pixel format per encoder when the source one is not accepted.
_DEFAULT_PIX = {
    "prores_ks": "yuv422p10le",
    "libx264": "yuv420p",
    "libx265": "yuv420p10le",
    "dnxhd": "yuv422p10le",
    "ffv1": "yuv444p16le",
}
_PRORES_PROFILES = {"proxy": 0, "lt": 1, "standard": 2, "hq": 3, "4444": 4, "4444xq": 5}


# --------------------------------------------------------------------------
# Sequences
# --------------------------------------------------------------------------

def frame_number(path: str) -> int | None:
    m = _FRAME_RE.match(os.path.basename(path))
    return int(m.group("num")) if m else None


def split_pattern(path: str) -> tuple[str, str, str, str] | None:
    """(folder, prefix, suffix, extension) of a frame pattern such as /shots/a/shot.####.exr; None for any other path."""
    m = _PATTERN_RE.match(os.path.basename(path))
    return (os.path.dirname(path), m.group("prefix"), m.group("suffix"), m.group("ext").lower()) if m else None


def is_sequence(path: str) -> bool:
    return os.path.isdir(path) or split_pattern(path) is not None


def pattern_of(prefix: str, suffix: str, ext: str, digits: int) -> str:
    return f"{prefix}{'#' * max(1, digits)}{suffix}{ext}"


def find_sequence(folder: str) -> list[str]:
    """Numbered frames of the largest image sequence in a folder, in order, a missing frame held from the one before."""
    return sequence_frames(folder)[0]


def sequence_frames(folder: str) -> tuple[list[str], int, list[int]]:
    """(one file per frame number, step, missing numbers) for the largest image sequence in a folder, or for the one a
    frame pattern names.

    As OpenRV's FileSequence maps frame numbers to files, a missing number keeps its place: the frame
    before it holds, so every later frame keeps its number. The step is the common gap between numbers
    (2 for frames on twos), so a sequence on twos is not mistaken for one with every other frame missing.
    """
    pattern = split_pattern(folder)
    if pattern:
        folder = pattern[0]
    groups: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMAGE_EXTS or ext in ANIMATIONS:
            continue
        m = _FRAME_RE.match(name)
        key = (m.group("prefix"), m.group("suffix"), ext) if m else (name, "", ext)
        if pattern and key != pattern[1:]:
            continue
        num = int(m.group("num")) if m else 0
        groups.setdefault(key, []).append((num, full))
    if not groups:
        raise FileNotFoundError(f"No image frames found in {folder if not pattern else os.path.join(folder, pattern_of(*pattern[1:], 4))}")
    key, best = max(groups.items(), key=lambda kv: len(kv[1]))
    if key[1] == "_":  # core Save Image's counter names (f_00001_.png): numbers count files, not frames
        return [p for _, p in sorted(best)], 1, []
    found = {}
    for num, path in sorted(best):
        found.setdefault(num, path)  # two files for one number: the first in name order
    nums = sorted(found)
    step = 0
    for a, b in zip(nums, nums[1:]):
        step = math.gcd(step, b - a)
    step = step or 1
    files, missing, last = [], [], found[nums[0]]
    for num in range(nums[0], nums[-1] + 1, step):
        if num in found:
            last = found[num]
        else:
            missing.append(num)
        files.append(last)
    return files, step, missing


# --------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------
def _fps_fields(fps_hint) -> dict:
    """The frame rate of a still plate, as a float and as an exact fraction."""
    rate = fps_hint if isinstance(fps_hint, Fraction) else Fraction(float(fps_hint or 24.0)).limit_denominator(100000)
    return {"fps": float(rate), "fps_num": rate.numerator, "fps_den": rate.denominator}


def exr_info(path: str) -> dict:
    """Header summary of one EXR frame: parts, channels, pixel types, compression."""
    if OpenEXR is None:
        return {"openexr": False}
    with OpenEXR.File(path, header_only=True) as f:
        parts = []
        for i, part in enumerate(f.parts):
            header = part.header
            chans = header.get("channels", [])
            names = []
            for c in chans:
                names.append(getattr(c, "name", str(c)))
            parts.append({
                "index": i,
                "name": header.get("name", ""),
                "channels": names,
                "compression": str(header.get("compression", "")),
                "dataWindow": str(header.get("dataWindow", "")),
                "displayWindow": str(header.get("displayWindow", "")),
                "chromaticities": str(header.get("chromaticities", "")),
            })
    rgb_part = next((p["index"] for p in parts if {"R", "G", "B"} <= set(p["channels"])), 0)
    extra = [c for p in parts for c in p["channels"] if not (p["index"] == rgb_part and c in ("R", "G", "B", "A"))]
    return {"openexr": True, "parts": parts, "rgb_part": rgb_part, "extra_channels": extra}


def probe_video(path: str) -> dict:
    if av is None:
        raise RuntimeError("PyAV is required to read video plates")
    with av.open(path) as c:
        vs = c.streams.video[0]
        cc = vs.codec_context
        rate = vs.average_rate or vs.guessed_rate or Fraction(24, 1)
        spec = {
            "container": c.format.name.split(",")[0],
            "codec": cc.name,
            "profile": (cc.profile or ""),
            "pix_fmt": cc.pix_fmt or (vs.format.name if vs.format else ""),
            "width": cc.width,
            "height": cc.height,
            "fps": float(rate),
            "fps_num": rate.numerator,
            "fps_den": rate.denominator,
            "bit_rate": int(cc.bit_rate or c.bit_rate or 0),
            "frames": int(vs.frames or 0),
            "timecode": next((st.metadata["timecode"] for st in c.streams if st.metadata.get("timecode")),
                             c.metadata.get("timecode", "")),
            "audio_streams": len(c.streams.audio),
        }
        for attr in ("color_primaries", "color_trc", "colorspace", "color_range"):
            value = getattr(cc, attr, None)
            spec[attr] = int(value) if value is not None else None
    return spec


def probe_still(path: str) -> dict:
    spec = {"pix_fmt": "", "width": 0, "height": 0}
    if av is not None:
        try:
            with av.open(path) as c:
                vs = c.streams.video[0]
                spec.update(pix_fmt=vs.codec_context.pix_fmt or "", width=vs.codec_context.width,
                            height=vs.codec_context.height, codec=vs.codec_context.name)
        except (AVError, IndexError):  # a still PyAV cannot open keeps the empty fields
            pass
    return spec


def probe_plate(path: str, fps_hint: float = 24.0) -> dict:
    """Spec of a plate: a video file or an animated image, a single image, a folder of frames, or a frame pattern."""
    if is_sequence(path):
        files, step, missing = sequence_frames(path)
        first = files[0]
        ext = os.path.splitext(first)[1].lower()
        spec = {"kind": "sequence", "source": path, "files": files, "ext": ext, "step": step, "missing": missing,
                "first_frame": frame_number(first) or 0, "frames": len(files), **_fps_fields(fps_hint)}
        spec.update({k: v for k, v in probe_still(first).items() if k not in spec})
        if ext == ".exr":
            spec["exr"] = exr_info(first)
        return spec
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTS or (ext in ANIMATIONS and probe_video(path)["frames"] != 1):
        spec = probe_video(path)
        spec.update({"kind": "video", "source": path, "ext": ext})
        return spec
    if ext in IMAGE_EXTS:
        spec = {"kind": "image", "source": path, "files": [path], "ext": ext, "frames": 1,
                "first_frame": frame_number(path) or 0, **_fps_fields(fps_hint)}
        spec.update({k: v for k, v in probe_still(path).items() if k not in spec})
        if ext == ".exr":
            spec["exr"] = exr_info(path)
        return spec
    raise ValueError(f"Unsupported plate: {path}")


def guess_color_space(spec: dict) -> str:
    """A starting guess from the file; the user can always override it in the app.

    EXR is scene-linear by convention: its chromaticities say which gamut.
    ACEScg (AP1) has its red primary at (0.713, 0.293).
    """
    trc = spec.get("color_trc")  # FFmpeg's numbers: 16 SMPTE ST 2084, 18 ARIB STD-B67, 8 linear
    if spec.get("kind") == "video" and trc in (16, 18, 8):
        return {16: "HDR PQ", 18: "HDR", 8: "linear"}[trc]
    if spec.get("ext") != ".exr":
        return "sRGB"
    for part in spec.get("exr", {}).get("parts", []):
        nums = [float(x) for x in re.findall(r"-?\d+\.\d+", part.get("chromaticities", ""))]
        if len(nums) >= 2 and abs(nums[0] - 0.713) < 0.002 and abs(nums[1] - 0.293) < 0.002:
            return "linear ACEScg"
    return "linear"


def spec_json(spec: dict) -> str:
    slim = {k: v for k, v in spec.items() if k != "files"}
    if "files" in spec:
        slim["file_count"] = len(spec["files"])
        slim["first_file"] = os.path.basename(spec["files"][0])
    return json.dumps(slim, indent=1, default=str)


def pad_count_8n1(n: int) -> int:
    """Smallest 8k+1 frame count that holds n frames (LTX needs 8k+1)."""
    return n if (n - 1) % 8 == 0 else n + (8 - (n - 1) % 8)


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def output_frame_name(spec: dict, index: int, out_dir: str, ext: str | None = None) -> str:
    ext = ext or spec.get("ext", ".exr")
    if spec.get("kind") in ("sequence", "image"):
        src = os.path.basename(spec["files"][min(index, len(spec["files"]) - 1)])
        m = _FRAME_RE.match(src)
        if m and spec.get("kind") == "sequence":
            num = spec["first_frame"] + index * spec.get("step", 1)
            return os.path.join(out_dir, f"{m.group('prefix')}{num:0{len(m.group('num'))}d}{m.group('suffix')}{ext}")
        stem = os.path.splitext(src)[0]
        return os.path.join(out_dir, f"{stem}{ext}")
    stem = os.path.splitext(os.path.basename(spec.get("source", "plate")))[0]
    return os.path.join(out_dir, f"{stem}.{index + spec.get('first_frame', 0):04d}{ext}")


RGB_NAMES = ("R", "G", "B")


def _window(header: dict, key: str) -> tuple[int, int, int, int]:
    """An EXR header's data or display window as (x0, y0, x1, y1), inclusive."""
    lo, hi = header[key]
    return int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1])


def _place(chans: dict, header: dict, new: dict, keep: np.ndarray | None) -> dict:
    """The part's channels with `new` (display-window arrays) written in, R, G and B keeping the source where `keep`
    holds; `header`'s data window grows when an edit put something outside it (write_exr_like)."""
    dx0, dy0, dx1, dy1 = _window(header, "dataWindow")
    px0, py0, px1, py1 = _window(header, "displayWindow")
    h, w = next(iter(new.values())).shape[:2]
    if (h, w) != (py1 - py0 + 1, px1 - px0 + 1):
        raise ValueError(f"Size mismatch: the frame is {w} x {h}, the display window {px1 - px0 + 1} x {py1 - py0 + 1}")
    inside = np.zeros((h, w), bool)  # the display pixels the data window holds
    inside[max(dy0 - py0, 0):max(dy1 - py0 + 1, 0), max(dx0 - px0, 0):max(dx1 - px0 + 1, 0)] = True
    made = np.zeros((h, w), bool)
    for arr in new.values():
        made |= arr != 0
    outside = made & ~inside if keep is None else made & ~inside & ~keep
    nx0, ny0, nx1, ny1 = dx0, dy0, dx1, dy1
    if outside.any():  # an edit beyond the data window: the smallest box that holds both
        ys, xs = np.nonzero(outside)
        nx0, ny0 = min(dx0, px0 + int(xs.min())), min(dy0, py0 + int(ys.min()))
        nx1, ny1 = max(dx1, px0 + int(xs.max())), max(dy1, py0 + int(ys.max()))
        header["dataWindow"] = (np.array([nx0, ny0], np.int32), np.array([nx1, ny1], np.int32))
    ix0, iy0, ix1, iy1 = max(nx0, px0), max(ny0, py0), min(nx1, px1), min(ny1, py1)  # the display inside the window
    out = {}
    for name, src in chans.items():
        a = np.zeros((ny1 - ny0 + 1, nx1 - nx0 + 1), src.dtype)
        a[dy0 - ny0:dy1 - ny0 + 1, dx0 - nx0:dx1 - nx0 + 1] = src
        if name in new and ix0 <= ix1 and iy0 <= iy1:
            at = (slice(iy0 - ny0, iy1 - ny0 + 1), slice(ix0 - nx0, ix1 - nx0 + 1))
            view = (slice(iy0 - py0, iy1 - py0 + 1), slice(ix0 - px0, ix1 - px0 + 1))
            value = new[name][view].astype(src.dtype)
            a[at] = value if keep is None or name not in RGB_NAMES else np.where(keep[view], a[at], value)
        out[name] = a
    return out


def write_exr_like(src_path: str, rgb: np.ndarray, alpha: np.ndarray | None, out_path: str,
                   keep: np.ndarray | None = None) -> None:
    """Write `rgb` (H, W, 3 float) into a copy of the source EXR frame.

    Every channel, part and header attribute of the source is kept. Only R, G and B (and A when `alpha` is given) of the
    RGB part are replaced, in the source pixel type. Where `keep` (H, W bool) is True, the source pixels stay bit-identical.

    `rgb`, `alpha` and `keep` cover the display window, as FFmpeg and core read an EXR: the data window's pixels at their
    place, zero where it holds none. The data window stays as it is unless an edit put something outside it; then it grows
    to the smallest box that holds the edit too, and the part's other channels are padded with zeros. Pixels of the data
    window outside the display window (overscan) stay the source's.
    """
    if OpenEXR is None:
        raise RuntimeError("OpenEXR is not installed")
    with OpenEXR.File(src_path, separate_channels=True) as f:
        parts_out = []
        rgb_done = False
        for part in f.parts:
            header = dict(part.header)
            header.pop("channels", None)  # rebuilt from the channel arrays
            chans = {name: ch.pixels for name, ch in part.channels.items()}
            if not rgb_done and set(RGB_NAMES) <= set(chans):
                new = {name: rgb[..., i] for i, name in enumerate(RGB_NAMES)}
                if alpha is not None and "A" in chans:
                    new["A"] = alpha
                chans = _place(chans, header, new, keep)
                rgb_done = True
            name = header.get("name")
            parts_out.append(OpenEXR.Part(header, chans, name=name) if name else (header, chans))
        if len(parts_out) == 1 and isinstance(parts_out[0], tuple):
            OpenEXR.File(parts_out[0][0], parts_out[0][1]).write(out_path)
        else:
            parts = [p if not isinstance(p, tuple) else OpenEXR.Part(p[0], p[1], name=f"part{i}")
                     for i, p in enumerate(parts_out)]
            OpenEXR.File(parts).write(out_path)

def read_native(path: str, with_alpha: bool, eight: bool = False) -> np.ndarray:
    """Read one still frame exactly, as integers (RGB or RGBA): 8 bits for an 8-bit target, else 16.

    Core decodes to float through swscale, which can move a 16-bit value by a few codes. The export copies untouched
    pixels from this exact read instead. An 8-bit frame is read at 8 bits: swscale's 16 to 8-bit step is not the
    inverse of its 8 to 16-bit one, and moved 123 of the 256 levels up by one (29 Oct 2026).
    """
    with av.open(path) as c:
        frame = next(c.decode(video=0))
        fmt = ("rgba" if with_alpha else "rgb24") if eight else ("rgba64le" if with_alpha else "rgb48le")
        return frame.to_ndarray(format=fmt)


def eight_bit_rgb(pix_fmt: str) -> bool:
    """True for an 8-bit RGB format (rgb24, rgba, bgra, gbrp): written from 8-bit values, so swscale only reorders bytes."""
    try:
        f = av.VideoFormat(pix_fmt)
        return bool(f.is_rgb) and not f.has_palette and all(c.bits == 8 for c in f.components)
    except (ValueError, TypeError, AVError):
        return False


PLANAR_FLOATS = {"gbrpf16le": "<f2", "gbrapf16le": "<f2", "gbrpf32le": "<f4", "gbrapf32le": "<f4"}


def read_float(path: str) -> np.ndarray:
    """One still frame in its own values, as float32 RGB (H, W, 3): an EXR's linear light above 1.0 and below 0 as stored,
    other formats scaled to 0 to 1. The viewer's colour tools read these, as OpenRV's cache keeps an EXR's half floats."""
    with av.open(path) as c:
        frame = next(c.decode(video=0))
        dtype = PLANAR_FLOATS.get(frame.format.name)
        if dtype:  # FFmpeg decodes EXR to planar floats in G, B, R order (half or float): read the planes, convert nothing
            planes = []
            for p in frame.planes[:3]:
                a = np.frombuffer(p, dtype)
                planes.append(a[: frame.height * (p.line_size // a.itemsize)].reshape(frame.height, -1)[:, : frame.width])
            g, b, r = planes
            return np.stack([r, g, b], -1).astype(np.float32)
        return frame.to_ndarray(format="rgb48le").astype(np.float32) / 65535.0


def write_pngs(frame_at, paths: list, workers: int = 8, level: int = 1, tick=None) -> None:
    """Write frame_at(i), an (H, W, 3 or 4) uint8 array, to paths[i] as PNG, several frames at once: PyAV releases the GIL
    while it compresses. Core Save Image writes one frame after another at zlib level 4: 35.3 s for 121 frames at
    1920 x 1088 on an RTX PRO 6000 pod (28 Oct). Level 1 compresses 3.5 times faster for files about 11% larger
    (one such frame: 111 ms against 392 ms, 3.08 MB against 2.78 MB)."""
    def one(i):
        a = np.ascontiguousarray(frame_at(i))
        fmt = "rgba" if a.shape[2] == 4 else "rgb24"
        c = av.CodecContext.create("png", "w")
        c.width, c.height, c.pix_fmt = a.shape[1], a.shape[0], fmt
        c.options = {"compression_level": str(level)}
        packets = c.encode(av.VideoFrame.from_ndarray(a, format=fmt)) + c.encode(None)
        with open(paths[i], "wb") as fh:
            fh.write(b"".join(bytes(p) for p in packets))
        if tick:
            tick()
    with ThreadPoolExecutor(max(1, workers)) as pool:
        list(pool.map(one, range(len(paths))))


def write_exrs(frame_at, paths: list, workers: int = 8, tick=None) -> None:
    """Write frame_at(i), an (H, W, 3) float array, to paths[i] as a half-float EXR with lossless PIZ compression, several
    frames at once: OpenEXR releases the GIL while it compresses (a 1080p frame: 83 ms, 5.3 MB, 29 Oct). These are the
    review frames the viewer reads at full precision; the export keeps the plate's own EXR layers and header instead."""
    def one(i):
        rgb = np.ascontiguousarray(np.nan_to_num(frame_at(i)[..., :3], nan=0.0, posinf=65504.0, neginf=-65504.0)
                                   .clip(-65504.0, 65504.0).astype(np.float16))
        with OpenEXR.File({"compression": OpenEXR.PIZ_COMPRESSION, "type": OpenEXR.scanlineimage}, {"RGB": rgb}) as f:
            f.write(paths[i])
        if tick:
            tick()
    with ThreadPoolExecutor(max(1, workers)) as pool:
        list(pool.map(one, range(len(paths))))


def scan_folder(folder: str) -> dict:
    """What the plate browser shows of a folder, from names, sizes and times alone, so a folder of thousands of ComfyUI
    outputs lists at once: subfolders, videos and animated images, saved scenes, and image sequences (numbered images
    grouped by name, each named by its frame pattern). An image alone in its group is not a plate: only counted."""
    items, groups, singles = [], {}, 0
    with os.scandir(folder) as it:
        for e in it:
            if e.name.startswith(".") or e.is_symlink():
                continue
            st = e.stat(follow_symlinks=False)
            if e.is_dir(follow_symlinks=False):
                items.append({"name": e.name, "kind": "folder", "mtime": st.st_mtime})
                continue
            ext = os.path.splitext(e.name)[1].lower()
            if ext in VIDEO_EXTS or ext in ANIMATIONS:
                items.append({"name": e.name, "kind": "video", "size": st.st_size, "mtime": st.st_mtime})
            elif e.name.endswith(".paintaplate.json"):
                items.append({"name": e.name, "kind": "scene", "size": st.st_size, "mtime": st.st_mtime})
            elif ext in IMAGE_EXTS:
                m = _FRAME_RE.match(e.name)
                if not m:
                    singles += 1
                    continue
                g = groups.setdefault((m.group("prefix"), m.group("suffix"), ext), {"files": 0, "size": 0, "mtime": 0.0,
                                                                                    "digits": len(m.group("num")), "first": e.name})
                g["files"] += 1
                g["size"] += st.st_size
                g["mtime"] = max(g["mtime"], st.st_mtime)
                g["first"] = min(g["first"], e.name)
    for (prefix, suffix, ext), g in groups.items():
        if g["files"] < 2:
            singles += 1
            continue
        items.append({"name": pattern_of(prefix, suffix, ext, g["digits"]), "kind": "sequence", "frames": g["files"],
                      "size": g["size"], "mtime": g["mtime"], "first": g["first"]})
    return {"items": items, "singles": singles}


def write_movie(frame_at, n: int, path: str, fps: float, workers: int = 8, crf: int = 18, preset: str = "veryfast",
                tick=None) -> None:
    """An H.264 movie for the page to play, as core Save Video makes it (crf 18, yuv420p, BT.709 matrix and primaries, the
    sRGB transfer tag, limited range), only faster: the frames convert to YUV several at once and x264 runs at preset
    veryfast with its own threads. Core took 8.3 s for 121 frames at 1920 x 1088 on an RTX PRO 6000 pod (28 Oct)."""
    first = np.ascontiguousarray(frame_at(0))
    h, w = first.shape[:2]
    with av.open(path, "w") as out:
        st = out.add_stream("libx264", rate=Fraction(fps).limit_denominator(1001))
        st.width, st.height, st.pix_fmt = w, h, "yuv420p"
        st.options = {"crf": str(crf), "preset": preset}
        cc = st.codec_context
        cc.thread_count = 0  # x264 picks its threads
        cc.color_primaries, cc.color_trc, cc.colorspace, cc.color_range = 1, 13, 1, 1  # BT.709, sRGB, BT.709, limited

        def yuv(i):  # swscale with the BT.709 matrix, full-range RGB in and limited range out, as core converts
            a = first if i == 0 else np.ascontiguousarray(frame_at(i))
            f = av.VideoFrame.from_ndarray(a, format="rgb24").reformat(format="yuv420p", dst_colorspace=1)
            if tick:
                tick()
            return f
        with ThreadPoolExecutor(max(1, workers)) as pool:
            for i, f in enumerate(pool.map(yuv, range(n))):
                f.pts = i
                for p in st.encode(f):
                    out.mux(p)
        for p in st.encode(None):
            out.mux(p)


def plane_array(plane, itemsize: int) -> np.ndarray:
    """One plane of a frame as (height, width) samples, without its line padding."""
    a = np.frombuffer(plane, np.uint16 if itemsize == 2 else np.uint8)
    return a[: plane.height * (plane.line_size // itemsize)].reshape(plane.height, -1)[:, : plane.width]


def keep_samples(frame, source, keep: np.ndarray):
    """`frame` (planar YUV) with `source`'s own samples wherever `keep` (H, W) holds for every pixel a sample covers.

    Untouched pixels then reach the encoder as the source's YUV samples, with no RGB round trip: a 4:2:0 plate lost up
    to 12/255 to that round trip, even with a lossless encode (42.25 dB, 28 Oct). A chroma sample shared by four pixels
    is kept only when all four are untouched.
    """
    itemsize = 2 if re.search(r"p1[0246]", frame.format.name) else 1
    out = av.VideoFrame(frame.width, frame.height, frame.format.name)
    for p_out, p_new, p_src in zip(out.planes, frame.planes, source.planes):
        a, b = plane_array(p_new, itemsize).copy(), plane_array(p_src, itemsize)
        fy, fx = max(1, round(keep.shape[0] / a.shape[0])), max(1, round(keep.shape[1] / a.shape[1]))
        k = np.zeros((a.shape[0] * fy, a.shape[1] * fx), bool)
        k[: min(keep.shape[0], k.shape[0]), : min(keep.shape[1], k.shape[1])] = keep[: k.shape[0], : k.shape[1]]
        k = k.reshape(a.shape[0], fy, a.shape[1], fx).all(axis=(1, 3))
        a[k] = b[k]
        buf = np.zeros((p_out.height, p_out.line_size // itemsize), a.dtype)
        buf[:, : a.shape[1]] = a
        p_out.update(buf.tobytes())
    out.pts = frame.pts
    return out


class SourceFrames:
    """The frames of a video file, decoded in order, in the pixel format the writer encodes."""

    def __init__(self, path: str, pix_fmt: str):
        self.container = av.open(path)
        self.frames = self.container.decode(video=0)
        self.pix_fmt = pix_fmt

    def next(self):
        f = next(self.frames, None)
        if f is None or f.format.name == self.pix_fmt:
            return f
        return f.reformat(format=self.pix_fmt)  # not the source's own samples, but the closest

    def close(self) -> None:
        self.container.close()


def to_uint16(rgb: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    data = np.clip(rgb, 0.0, 1.0)
    if alpha is not None:
        data = np.concatenate([data, np.clip(alpha, 0.0, 1.0)[..., None]], axis=-1)
    return (data * 65535.0 + 0.5).astype(np.uint16)


def to_uint8(rgb: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    data = np.clip(rgb, 0.0, 1.0)
    if alpha is not None:
        data = np.concatenate([data, np.clip(alpha, 0.0, 1.0)[..., None]], axis=-1)
    return (data * 255.0 + 0.5).astype(np.uint8)


def encode_still(rgb: np.ndarray, alpha: np.ndarray | None, codec: str, pix_fmt: str,
                 options: dict | None = None) -> bytes:
    """Encode one frame with a PyAV image codec (png, tiff, dpx, exr).

    `rgb` is float (H, W, 3), or uint8 or uint16 (H, W, 3 or 4) already quantised; floats for an 8-bit format are
    rounded here, not by swscale.
    PyAV takes planar float formats as (H, W, C) arrays in RGB order.
    """
    if av is None:
        raise RuntimeError("PyAV is required")
    h, w = rgb.shape[:2]
    if codec == "exr":
        data = rgb.astype(np.float32)
        fmt = "gbrpf32le"
        if alpha is not None:
            data = np.concatenate([data, alpha.astype(np.float32)[..., None]], axis=-1)
            fmt = "gbrapf32le"
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(data), format=fmt)
    else:
        if rgb.dtype in (np.uint8, np.uint16):
            arr = rgb
        else:
            arr = to_uint8(rgb, alpha) if eight_bit_rgb(pix_fmt) else to_uint16(rgb, alpha)
        if arr.dtype == np.uint8:
            fmt = "rgba" if arr.shape[-1] == 4 else "rgb24"
        else:
            fmt = "rgba64le" if arr.shape[-1] == 4 else "rgb48le"
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(arr), format=fmt)
    cc = av.CodecContext.create(codec, "w")
    cc.width, cc.height = w, h
    cc.pix_fmt = pix_fmt
    cc.time_base = Fraction(1, 1)
    if options:
        cc.options = options
    frame = frame.reformat(format=pix_fmt)
    packets = list(cc.encode(frame)) + list(cc.encode(None))
    return b"".join(bytes(p) for p in packets)


def still_target(spec: dict, has_alpha: bool) -> tuple[str, str, dict]:
    """(codec, pix_fmt, options) that matches a still source as closely as PyAV allows."""
    ext = spec.get("ext", ".png")
    src_fmt = spec.get("pix_fmt", "") or ""
    deep = any(t in src_fmt for t in ("48", "64", "16", "10", "12", "f32", "f16"))
    if ext == ".exr":
        half = "f16" in src_fmt or "half" in src_fmt or not src_fmt
        return "exr", ("gbrapf32le" if has_alpha else "gbrpf32le"), {"format": "half" if half else "float", "compression": "zip16"}
    if ext == ".png":
        return "png", ("rgba64be" if has_alpha else "rgb48be") if deep else ("rgba" if has_alpha else "rgb24"), {}
    if ext in (".tif", ".tiff"):
        return "tiff", ("rgba64le" if has_alpha else "rgb48le") if deep else ("rgba" if has_alpha else "rgb24"), {}
    if ext == ".dpx":
        if has_alpha:  # FFmpeg's DPX encoder writes alpha as RGBA, 8 or 16 bits
            return "dpx", "rgba64le" if deep else "rgba", {}
        if "12" in src_fmt:
            return "dpx", "gbrp12le", {}
        if "10" in src_fmt:
            return "dpx", "gbrp10le", {}
        return "dpx", "rgb48le" if deep else "rgb24", {}
    return "png", "rgb48be", {}


def carries_alpha(pix_fmt: str) -> bool:
    """True when a pixel format holds alpha (rgba, rgba64be, ya16be, gbrap10le, yuva444p10le)."""
    if av is None or not pix_fmt:
        return False
    try:
        return any(c.is_alpha for c in av.VideoFormat(pix_fmt).components)
    except (ValueError, TypeError, AVError):
        return False


def write_still(spec: dict, index: int, rgb: np.ndarray, alpha: np.ndarray | None, keep: np.ndarray | None,
                out_dir: str) -> str:
    """Frame `index` of an image or sequence plate, written in its own format under its own name in `out_dir`; returns
    the path. Where `keep` (H, W) holds, the source's exact pixels. The plate's own alpha stays sample for sample, since
    no edit works on it, unless a new `alpha` is given."""
    src, out = spec["files"][index], output_frame_name(spec, index, out_dir)
    if spec["ext"] == ".exr" and OpenEXR is not None:
        write_exr_like(src, rgb, alpha, out, keep=keep)
        return out
    own = alpha is None and carries_alpha(spec.get("pix_fmt", ""))
    codec, pix_fmt, options = still_target(spec, alpha is not None or own)
    data, a = rgb, alpha
    if codec != "exr" and (keep is not None or own):  # the source's exact integers, at its own depth
        eight = eight_bit_rgb(pix_fmt)
        native = read_native(src, alpha is not None or own, eight)
        new = to_uint8(rgb, alpha) if eight else to_uint16(rgb, alpha)
        if own:
            new = np.concatenate([new, native[..., 3:]], axis=-1)  # the plate's own alpha
        data, a = (new if keep is None else np.where(keep[..., None], native, new)), None
    with open(out, "wb") as f:
        f.write(encode_still(data, a, codec, pix_fmt, options))
    return out


def write_blank(path: str, width: int, height: int, fps: float, frames: int) -> str:
    """A black ProRes 4444 plate with Rec. 709 tags: the canvas of a fluid shot.

    ProRes codes every frame on its own, so one black frame is encoded and its packet written `frames` times: a
    1920 x 1088 x 121 canvas takes about a second instead of half a minute.
    """
    if av is None:
        raise RuntimeError("PyAV is required")
    rate = Fraction(fps).limit_denominator(1001)
    with av.open(path, "w") as out:
        stream = out.add_stream("prores_ks", rate=rate)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv444p10le"
        cc = stream.codec_context
        cc.color_primaries = cc.color_trc = cc.colorspace = 1  # Rec. 709
        cc.color_range = 1  # limited range, as ProRes
        cc.options = {"profile": "4"}  # 4444
        black = av.VideoFrame.from_ndarray(np.zeros((height, width, 3), np.uint16), format="rgb48le")
        try:
            frame = black.reformat(format="yuv444p10le", dst_colorspace=1, src_color_range=2, dst_color_range=1)
        except (ValueError, TypeError, AVError):  # an older PyAV without colour-range arguments
            frame = black.reformat(format="yuv444p10le")
        frame.pts = 0
        first = (list(stream.encode(frame)) + list(stream.encode(None)))[0]
        data, base, step = bytes(first), first.time_base, first.duration or 1
        for i in range(frames):
            packet = av.Packet(data)
            packet.stream, packet.time_base, packet.pts, packet.dts, packet.duration = stream, base, i * step, i * step, step
            packet.is_keyframe = True
            out.mux(packet)
    return path


def encoder_pix_fmt(encoder: str, want: str) -> str:
    """The pixel format nearest `want` that `encoder` writes: the same chroma layout at the highest depth it offers.

    FFmpeg's ProRes decoder reports a 4444 plate as yuv444p12le, and prores_ks writes yuv444p10le: asked to open with
    the decoder's format, the encoder refused it and the export failed.
    """
    try:
        offered = [f.name for f in (av.codec.Codec(encoder, "w").video_formats or [])]
    except (AVError, ValueError, TypeError):
        offered = []
    if not offered or want in offered:
        return want
    family = lambda f: (re.match(r"^([a-z]+\d*)p", f) or re.match(r"^(.*)$", f)).group(1)  # yuv444, yuva444, yuv420, gbr
    depth = lambda f: int((re.findall(r"p(\d+)", f) or ["8"])[0])
    same = [f for f in offered if family(f) == family(want)]
    if same:
        return max(same, key=depth)
    return _DEFAULT_PIX.get(encoder) if _DEFAULT_PIX.get(encoder) in offered else offered[0]


class VideoWriter:
    """Encode frames in the source codec, pixel format, colour tags and timecode.

    Falls back to ProRes 4444 in a .mov when the source encoder is missing.
    Audio from the source file is copied packet for packet on close().
    """

    def __init__(self, spec: dict, out_path: str, audio_source: str | None = None):
        if av is None:
            raise RuntimeError("PyAV is required")
        self.spec = spec
        self.notes: list[str] = []
        codec = spec.get("codec", "prores")
        encoder = _ENCODERS.get(codec, codec)
        if encoder not in av.codecs_available:
            self.notes.append(f"Encoder {encoder} not available: writing ProRes 4444 instead.")
            encoder, out_path = "prores_ks", os.path.splitext(out_path)[0] + ".mov"
        self.path = out_path
        self.out = av.open(out_path, "w")
        rate = Fraction(spec.get("fps_num") or 24, spec.get("fps_den") or 1)
        self.stream = self.out.add_stream(encoder, rate=rate)
        self.stream.width = spec["width"]
        self.stream.height = spec["height"]
        pix = spec.get("pix_fmt") or _DEFAULT_PIX.get(encoder, "yuv420p")
        if (written := encoder_pix_fmt(encoder, pix)) != pix:
            self.notes.append(f"{encoder} does not write {pix}: using {written}.")
            pix = written
        try:
            self.stream.pix_fmt = pix
        except (ValueError, AVError):
            pix = _DEFAULT_PIX.get(encoder, "yuv420p")
            self.stream.pix_fmt = pix
            self.notes.append(f"Pixel format {spec.get('pix_fmt')} refused by {encoder}: using {pix}.")
        self.pix_fmt = pix
        self.eight = eight_bit_rgb(pix)  # written from 8-bit values (write)
        cc = self.stream.codec_context
        for attr in ("color_primaries", "color_trc", "colorspace", "color_range"):
            value = spec.get(attr)
            if value is not None:
                try:
                    setattr(cc, attr, value)
                except (ValueError, TypeError, AVError):
                    self.notes.append(f"Could not copy {attr}.")
        opts = {}
        if encoder == "prores_ks":
            prof = str(spec.get("profile", "")).lower().replace(" ", "")
            opts["profile"] = str(next((v for k, v in sorted(_PRORES_PROFILES.items(), key=lambda kv: -len(kv[0])) if k in prof), 4 if "444" in pix else 3))
        elif encoder in ("libx264", "libx265"):
            # crf 8 is visually lossless: the codec is the only loss on untouched pixels. The preset trades encode
            # time for file size at the same quality; medium encodes about twice as fast as slow (checked on x264).
            opts["crf"] = "8"
            opts["preset"] = "medium"
        cc.options = opts
        if spec.get("timecode"):
            self.stream.metadata["timecode"] = spec["timecode"]
        # Streams must all exist before the first packet is written.
        self.audio_in = self.audio_out = None
        if audio_source and spec.get("audio_streams"):
            try:
                self.audio_in = av.open(audio_source)
                self.audio_out = self.out.add_stream_from_template(self.audio_in.streams.audio[0])
            except (AVError, OSError, IndexError, ValueError) as exc:  # audio is a convenience, never a failure
                self.notes.append(f"Audio not copied: {exc}")
                self.audio_in = None
        self.index = 0
        self.samples_kept = False  # a frame kept the source's own samples: close() says so in the notes
        self.dst_colorspace = spec.get("colorspace")
        self.dst_range = spec.get("color_range")

    def write(self, rgb: np.ndarray, keep: np.ndarray | None = None, source=None) -> None:
        """`rgb` is display-referred float (H, W, 3) in 0..1, as decoded by core. Where `keep` (H, W) holds, the source
        frame's own YUV samples are written instead (`keep_samples`)."""
        if self.eight:  # 8-bit RGB: rounded here, since swscale's 16 to 8-bit step moves most levels up by one
            frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(to_uint8(rgb)), format="rgb24")
        else:
            frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(to_uint16(rgb)), format="rgb48le")
        kwargs = {"format": self.pix_fmt}
        if self.dst_colorspace not in (None, 2):  # 2 = unspecified
            kwargs["dst_colorspace"] = self.dst_colorspace
        if self.pix_fmt.startswith("yuv") and self.dst_range in (None, 0, 1):  # limited range video
            kwargs["src_color_range"] = 2  # full range RGB in
            kwargs["dst_color_range"] = 1
        try:
            frame = frame.reformat(**kwargs)
        except (ValueError, TypeError, AVError):  # an older PyAV without colour-range arguments
            frame = frame.reformat(format=self.pix_fmt)
        if keep is not None and source is not None and self.pix_fmt.startswith("yuv"):
            frame = keep_samples(frame, source, keep)
            self.samples_kept = True
        frame.pts = self.index
        self.index += 1
        for packet in self.stream.encode(frame):
            self.out.mux(packet)

    def close(self) -> None:
        for packet in self.stream.encode(None):
            self.out.mux(packet)
        if self.audio_in is not None:
            a_in = self.audio_in.streams.audio[0]
            limit = self.index / float(self.spec.get("fps") or 24.0)
            for packet in self.audio_in.demux(a_in):
                if packet.dts is None:
                    continue
                if packet.pts is not None and float(packet.pts * a_in.time_base) > limit:
                    break
                packet.stream = self.audio_out
                self.out.mux(packet)
            self.audio_in.close()
        self.out.close()
        if self.samples_kept:
            self.notes.append("Untouched pixels are the source's own YUV samples.")
