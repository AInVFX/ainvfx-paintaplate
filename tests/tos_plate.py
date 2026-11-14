"""Fetches shot 05_4a of Tears of Steel, frames 480 to 600, into ComfyUI's input folder as plates/tos_05_4a.

121 half-float EXR frames of 1920 x 1012, scene-linear with Rec.709 primaries, 24 fps, from Xiph.org: 794 MB. Each frame is
checked (an EXR file's first four bytes) and written whole, so a second run fetches only the frames that are missing.
The credit stays with the frames, in CREDIT.txt: (CC) Blender Foundation | mango.blender.org, CC BY 3.0.

  python tests/tos_plate.py --comfy /data/ComfyUI
"""
import argparse
import os
import sys
import time
import urllib.error
import urllib.request

URL = "https://media.xiph.org/tearsofsteel/tearsofsteel-footage-exr/05_4a/linear_hd/"
SHOT, FRAMES, FOLDER = "05_4a", "480-600", "plates/tos_05_4a"
EXR = b"\x76\x2f\x31\x01"  # the magic number of every EXR file
CREDIT = ("Tears of Steel, shot 05_4a: (CC) Blender Foundation | mango.blender.org\n"
          "Licence: Creative Commons Attribution 3.0, https://creativecommons.org/licenses/by/3.0/\n"
          f"Source: {URL}\n")


def name(number: int) -> str:
    return f"{SHOT}_{number:05d}.exr"


def fetch(url: str, path: str, tries: int = 3) -> int:
    """One frame to `path`, through a temporary file, so a frame on disk is always whole. Its size in bytes."""
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            break
        except OSError as exc:  # urllib.error.URLError and HTTPError are OSErrors
            if attempt == tries or isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                raise
            time.sleep(2 * attempt)
    if data[:4] != EXR:
        raise ValueError("not an EXR file")
    with open(path + ".part", "wb") as f:
        f.write(data)
    os.replace(path + ".part", path)
    return len(data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--comfy", default="/data/ComfyUI", help=f"ComfyUI's folder: the frames go to input/{FOLDER} there")
    ap.add_argument("--url", default=URL, help="the folder the frames come from")
    ap.add_argument("--frames", default=FRAMES, help=f"the first and last frame numbers (default {FRAMES})")
    a = ap.parse_args(argv)
    first, last = (int(n) for n in a.frames.split("-"))
    if not os.path.isdir(os.path.join(a.comfy, "input")):
        print(f"ComfyUI's input folder not found: {os.path.join(a.comfy, 'input')}.\n  Give ComfyUI's folder with --comfy.")
        return 1
    folder = os.path.join(a.comfy, "input", FOLDER)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "CREDIT.txt"), "w") as f:
        f.write(CREDIT)
    count, got, size, t0 = last - first + 1, 0, 0, time.time()
    for number in range(first, last + 1):
        path = os.path.join(folder, name(number))
        if os.path.exists(path):
            continue
        try:
            size += fetch(a.url.rstrip("/") + "/" + name(number), path)
        except (OSError, ValueError) as exc:
            print(f"Frame {number} not fetched ({exc}).\n  Run the script again: it fetches only the frames that are missing.")
            return 1
        got += 1
        if got % 10 == 0:
            print(f"Fetched {got} of {count} frames.", flush=True)
    print(f"Plate ready: {count} frames in {folder}.\n  Fetched now: {got} {'frame' if got == 1 else 'frames'}, "
          f"{size / 1e6:,.0f} MB, done in {time.time() - t0:.1f} s.\n  Credit: (CC) Blender Foundation | mango.blender.org, "
          "CC BY 3.0, in CREDIT.txt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
