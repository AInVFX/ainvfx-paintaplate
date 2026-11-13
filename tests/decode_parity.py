"""Our video decoder against core's, frame for frame (PL7): plateio.decode_video and core's VideoFromFile, as Load Plate
called it, must make the same bytes. Run it with ComfyUI's Python, which has core and torch:

  /data/ComfyUI/.venv/bin/python tests/decode_parity.py --comfy /data/ComfyUI [--plates FILE ...] [--max-frames 17 121]

It makes its own movies (8 and 10 bits, full and limited range, widths on and off a multiple of 32, alpha) and reads the
plates named with --plates. One line per movie and trim, then DECODE SAME, or DECODE DIFFERS with exit code 1.
tests/comfy_live.py runs it, so a ComfyUI pin that changes core's pictures fails the live tests."""
import argparse
import os
import sys
import tempfile

import av
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plateio  # noqa: E402

KINDS = (("h264_256.mp4", "libx264", "yuv420p", 256, 144, None, "rgb24"),
         ("h264_200.mp4", "libx264", "yuv420p", 200, 112, None, "rgb24"),  # core pads it to 224 with a smeared border
         ("mjpeg_yuvj.mov", "mjpeg", "yuvj420p", 192, 108, None, "rgb24"),  # full range: core's 8-bit path
         ("prores10_192.mov", "prores_ks", "yuv422p10le", 192, 108, None, "rgb24"),
         ("prores10_200.mov", "prores_ks", "yuv422p10le", 200, 112, None, "rgb24"),
         ("prores4444_alpha.mov", "prores_ks", "yuva444p10le", 192, 108, {"profile": "4"}, "rgba"),
         ("png_rgba.mov", "png", "rgba", 160, 90, None, "rgba"),
         ("x264_10bit.mp4", "libx264", "yuv420p10le", 192, 108, None, "rgb24"),
         ("ffv1_gbrp10.mkv", "ffv1", "gbrp10le", 200, 112, None, "rgb24"))


def movies(folder: str, n: int = 30) -> list:
    """The test movies this PyAV can encode, 30 frames at 24 fps of moving gradients."""
    made = []
    for name, codec, pix_fmt, w, h, options, src in KINDS:
        path = os.path.join(folder, name)
        try:
            with av.open(path, "w") as c:
                s = c.add_stream(codec, rate=24)
                s.width, s.height, s.pix_fmt = w, h, pix_fmt
                if options:
                    s.options = options
                y, x = np.mgrid[0:h, 0:w]
                for i in range(n):
                    f = np.stack([(x * 255 // w + 3 * i) % 256, (y * 255 // h) % 256, ((x + y + 5 * i) * 2) % 256], -1)
                    if src == "rgba":
                        f = np.concatenate([f, ((7 * x + i) % 256)[..., None]], -1)
                    for p in s.encode(av.VideoFrame.from_ndarray(f.astype(np.uint8), format=src)):
                        c.mux(p)
                for p in s.encode():
                    c.mux(p)
            made.append(path)
        except Exception as e:  # an encoder this PyAV lacks
            print(f"{name}: not made here ({type(e).__name__})")
    return made


def same(video_from_file, path: str, max_frames: int):
    """(the same bytes, frames decoded, height, width): core's decode as Load Plate called it, and ours."""
    fps = plateio.probe_plate(path)["fps"]
    c = video_from_file(path, duration=max_frames / fps).get_components()
    core_rgb = np.ascontiguousarray(c.images[:max_frames].cpu().numpy())
    core_alpha = None if c.alpha is None else np.ascontiguousarray(c.alpha[:max_frames, ..., -1].cpu().numpy())
    rgb, alpha, n = plateio.decode_video(path, max_frames, fps)
    ok = rgb.shape == core_rgb.shape and rgb.tobytes() == core_rgb.tobytes() and (alpha is None) == (core_alpha is None) \
        and (alpha is None or alpha.tobytes() == core_alpha.tobytes())
    return ok, n, rgb.shape[1:3]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comfy", required=True, help="ComfyUI's folder: its core decoder is imported from there")
    ap.add_argument("--plates", nargs="*", default=[], help="more movies to compare, such as the laptop's plates")
    ap.add_argument("--max-frames", type=int, nargs="+", default=[17, 121])
    a = ap.parse_args()
    sys.path.insert(0, a.comfy)
    from comfy_api.v0_0_2 import InputImpl  # as nodes.py imports it
    differ = 0
    with tempfile.TemporaryDirectory() as tmp:
        for path in movies(tmp) + a.plates:
            for mf in a.max_frames:
                ok, n, (h, w) = same(InputImpl.VideoFromFile, path, mf)
                differ += not ok
                print(f"{os.path.basename(path)}, at most {mf} frames: {'the same bytes' if ok else 'DIFFERENT'}, {n} frames, {w} x {h}")
    print("DECODE SAME" if not differ else f"DECODE DIFFERS on {differ}")
    sys.exit(1 if differ else 0)
