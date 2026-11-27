"""An export's zip rebuilt from its own files, stage by stage, as a compositor rebuilds it: plate x (1 - matte) + layer x
matte against the zip's composite. Each row is read as Load Plate reads it (plateio.read_float for frames,
plateio.decode_video for a movie, at the movie's own frame rate). The matte is the zip's own at each stage: the plate-size
matte at full size and in SDR to HDR's set, the upscaled matte in Upscale's sets.

  python tests/zip_rebuild.py ~/Downloads/desk_v1_hdr_upscaled.zip [more zips]

For each zip, a table: each stage the zip holds, the frames of its plate, layer, matte and composite, then the largest and
the mean difference over every pixel of every frame, on values from 0 to 1, and the largest relative to the composite's
own value where it is above 1.0 (SDR to HDR's values). A stage that lacks a row names it.
"""
import os
import sys
import tempfile
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import plateio  # noqa: E402
import zip_rows  # noqa: E402

# Each stage: its name, the rows its plate may have, then its layer, matte and composite rows (zip_rows.ROWS)
STAGES = (("full size", ("source_plate", "fluid_shot_full_size"), "layer_full_size", "matte", "composite_full_size"),
          ("upscaled", ("plate_upscaled",), "layer_upscaled", "matte_upscaled", "composite_upscaled"),
          ("HDR", ("plate_hdr",), "layer_hdr", "matte", "composite_hdr"),  # the matte: one picture, the full size's
          ("HDR, upscaled", ("plate_hdr_upscaled",), "layer_hdr_upscaled", "matte_upscaled", "composite_hdr_upscaled"))


def read(z, row, into, frames):
    """One row of the zip as Load Plate reads it: its frames in order, or its one movie's first `frames` frames."""
    names = zip_rows.files(z.namelist(), row)
    z.extractall(into, names)
    if len(names) == 1 and os.path.splitext(names[0])[1].lower() in plateio.VIDEO_EXTS:
        path = os.path.join(into, names[0])
        return np.asarray(plateio.decode_video(path, frames, plateio.probe_plate(path)["fps"])[0], np.float32)[:frames]
    return np.stack([plateio.read_float(os.path.join(into, n)) for n in sorted(names)])


def rebuilt(z, into, frames=0):
    """By stage the zip holds a row of: (the frames of the plate, layer, matte and composite, the largest difference, the
    mean, the largest relative to max(1, the composite)), or the rows it lacks as a string. `frames`: how many frames a
    movie gives, the matte's own count when 0."""
    names, found = z.namelist(), {}
    for stage, plates, *rows in STAGES:
        plate = next((p for p in plates if zip_rows.files(names, p)), plates[0])
        held = [r for r in (plate, *rows) if zip_rows.files(names, r)]
        if not held:
            continue
        if len(held) < 4:
            found[stage] = "lacks " + ", ".join(r for r in (plate, *rows) if r not in held)
            continue
        n = frames or len(zip_rows.files(names, rows[1]))
        p, l, m, c = (read(z, r, into, n) for r in (plate, *rows))
        counts = tuple(len(a) for a in (p, l, m, c))
        if len(set(counts)) > 1 or len({a.shape[1:3] for a in (p, l, m, c)}) > 1:
            found[stage] = counts + (float("nan"),) * 3
            continue
        d = np.abs(p[..., :3] * (1 - m[..., :1]) + l[..., :3] * m[..., :1] - c[..., :3])
        found[stage] = counts + (float(d.max()), float(d.mean()), float((d / np.maximum(1.0, np.abs(c[..., :3]))).max()))
    return found


def table(path):
    """The zip's stages as a Markdown table."""
    with tempfile.TemporaryDirectory() as into, zipfile.ZipFile(path) as z:
        found = rebuilt(z, into)
    lines = [f"## {os.path.basename(path)}", "", "| Stage | Frames: plate, layer, matte, composite | Largest | Mean | Largest, relative |",
             "| --- | --- | --- | --- | --- |"]
    for stage, v in found.items():
        lines.append(f"| {stage} | {v} | | | |" if isinstance(v, str) else f"| {stage} | {', '.join(map(str, v[:4]))} | {v[4]:.6f} | {v[5]:.6f} | {v[6]:.6f} |")
    return "\n".join(lines + [""])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print("\n".join(table(p) for p in sys.argv[1:]))
