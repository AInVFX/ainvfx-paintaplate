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
# The last number in a name is the frame: "shot.1001.exr", and also "f_00001_.png" as core Save Image writes.
_FRAME_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)(?P<suffix>[^\d]*?)(?P<ext>\.[A-Za-z0-9]+)$")

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


def find_sequence(folder: str) -> list[str]:
    """Numbered frames of the largest image sequence in a folder, in order, a missing frame held from the one before."""
    return sequence_frames(folder)[0]


def sequence_frames(folder: str) -> tuple[list[str], int, list[int]]:
    """(one file per frame number, step, missing numbers) for the largest image sequence in a folder.

    As OpenRV's FileSequence maps frame numbers to files, a missing number keeps its place: the frame
    before it holds, so every later frame keeps its number. The step is the common gap between numbers
    (2 for frames on twos), so a sequence on twos is not mistaken for one with every other frame missing.
    """
    groups: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMAGE_EXTS:
            continue
        m = _FRAME_RE.match(name)
        key = (m.group("prefix"), m.group("suffix"), ext) if m else (name, "", ext)
        num = int(m.group("num")) if m else 0
        groups.setdefault(key, []).append((num, full))
    if not groups:
        raise FileNotFoundError(f"No image frames found in {folder}")
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
    """Spec of a plate: a video file, a single image, or a folder of frames."""
    if os.path.isdir(path):
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
    if ext in VIDEO_EXTS:
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


def write_exr_like(src_path: str, rgb: np.ndarray, alpha: np.ndarray | None, out_path: str,
                   keep: np.ndarray | None = None, extra_overrides: dict | None = None) -> None:
    """Write `rgb` (H, W, 3 float) into a copy of the source EXR frame.

    Every channel, part and header attribute of the source is kept. Only R, G,
    B (and A when `alpha` is given) of the RGB part are replaced, in the source
    pixel type. Where `keep` (H, W bool) is True, the source pixels stay
    bit-identical. `extra_overrides` maps other channel names to new 2D arrays
    (for a regenerated alpha or depth).
    """
    if OpenEXR is None:
        raise RuntimeError("OpenEXR is not installed")
    extra_overrides = extra_overrides or {}
    with OpenEXR.File(src_path, separate_channels=True) as f:
        parts_out = []
        rgb_done = False
        for part in f.parts:
            header = dict(part.header)
            header.pop("channels", None)  # rebuilt from the channel arrays
            chans = {name: ch.pixels for name, ch in part.channels.items()}
            if not rgb_done and {"R", "G", "B"} <= set(chans):
                for i, name in enumerate(("R", "G", "B")):
                    src = chans[name]
                    if src.shape != rgb.shape[:2]:
                        raise ValueError(f"Size mismatch for {name}: {src.shape} vs {rgb.shape[:2]}")
                    new = rgb[..., i].astype(src.dtype)
                    chans[name] = new if keep is None else np.where(keep, src, new)
                if alpha is not None and "A" in chans:
                    chans["A"] = alpha.astype(chans["A"].dtype)
                rgb_done = True
            for name, arr in extra_overrides.items():
                if name in chans:
                    chans[name] = arr.astype(chans[name].dtype)
            name = header.get("name")
            parts_out.append(OpenEXR.Part(header, chans, name=name) if name else (header, chans))
        if len(parts_out) == 1 and isinstance(parts_out[0], tuple):
            OpenEXR.File(parts_out[0][0], parts_out[0][1]).write(out_path)
        else:
            parts = [p if not isinstance(p, tuple) else OpenEXR.Part(p[0], p[1], name=f"part{i}")
                     for i, p in enumerate(parts_out)]
            OpenEXR.File(parts).write(out_path)


def read_native(path: str, with_alpha: bool) -> np.ndarray:
    """Read one still frame exactly, as 16-bit integers (RGB or RGBA).

    Core decodes to float through swscale, which can move a 16-bit value by a
    few codes. The export copies untouched pixels from this exact read instead.
    """
    with av.open(path) as c:
        frame = next(c.decode(video=0))
        return frame.to_ndarray(format="rgba64le" if with_alpha else "rgb48le")


def to_uint16(rgb: np.ndarray, alpha: np.ndarray | None = None) -> np.ndarray:
    data = np.clip(rgb, 0.0, 1.0)
    if alpha is not None:
        data = np.concatenate([data, np.clip(alpha, 0.0, 1.0)[..., None]], axis=-1)
    return (data * 65535.0 + 0.5).astype(np.uint16)


def encode_still(rgb: np.ndarray, alpha: np.ndarray | None, codec: str, pix_fmt: str,
                 options: dict | None = None) -> bytes:
    """Encode one frame with a PyAV image codec (png, tiff, dpx, exr).

    `rgb` is float (H, W, 3), or uint16 (H, W, 3 or 4) already quantised.
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
        arr = rgb if rgb.dtype == np.uint16 else to_uint16(rgb, alpha)
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
        if "12" in src_fmt:
            return "dpx", "gbrp12le", {}
        if "10" in src_fmt:
            return "dpx", "gbrp10le", {}
        return "dpx", "rgb48le" if deep else "rgb24", {}
    return "png", "rgb48be", {}


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
        self.dst_colorspace = spec.get("colorspace")
        self.dst_range = spec.get("color_range")

    def write(self, rgb: np.ndarray) -> None:
        """`rgb` is display-referred float (H, W, 3) in 0..1, as decoded by core."""
        arr = np.ascontiguousarray((np.clip(rgb, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16))
        frame = av.VideoFrame.from_ndarray(arr, format="rgb48le")
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
