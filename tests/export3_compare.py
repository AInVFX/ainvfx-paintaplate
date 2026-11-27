"""The largest difference between the frames that Finish's ComfyUI graph wrote and the page's own, as Export's zip holds
them. Run Finish's graph in ComfyUI first: drop the zip's *_comfyui_graph.json of Finish on ComfyUI's canvas, then Run.

    /data/ComfyUI/.venv/bin/python tests/export3_compare.py --output /data/ComfyUI/output

--zip names the export's zip; by default, the newest zip in ~/Downloads that holds Finish's graph. Each result of Finish's
steps that the zip holds is compared with what the graph wrote, frame by frame, in floats: « Plate, HDR » and the other HDR
elements, the upscaled parts and the upscaled matte. The graph names its own folders (its Save Plate and Save Frames nodes);
the zip names the page's by row. A movie is read at 16 bits per channel, frames as they are. Nothing is written."""
import argparse
import glob
import json
import os
import re
import sys
import tempfile
import zipfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plateio  # noqa: E402

FINISH = ("finish_comfyui_graph", "comfyui_graph")  # Finish's graph: beside other graphs, or alone (logic.graphRows)
JOB = re.compile(r" · job \d+ · ")  # a title of Finish's graph names its job (graph.finishGraph)
SAVES = {"PaintAPlate_SavePlate", "PaintAPlate_SaveFrames"}


def finish_graph(z):
    """Finish's API graph in the zip, or None: the graph whose nodes name their jobs."""
    for row in FINISH:
        for name in z.namelist():
            if name.endswith(f"_{row}.json") and "/" not in name:
                api = (json.loads(z.read(name)).get("extra") or {}).get("paintaplate", {}).get("prompt") or {}
                if any(JOB.search(n.get("_meta", {}).get("title", "")) for n in api.values()):
                    return api
    return None


def newest_zip(folder):
    for path in sorted(glob.glob(os.path.join(os.path.expanduser(folder), "*.zip")), key=os.path.getmtime, reverse=True):
        with zipfile.ZipFile(path) as z:
            if finish_graph(z):
                return path
    sys.exit(f"No zip in {folder} holds Finish's graph: export with « ComfyUI graph » ticked and a Finish switch on.")


def row_of(folder):
    """The zip's row for a folder Finish's graph writes, relative to the graphs' folder, or None (a window, a movie)."""
    m = re.fullmatch(r"hdr/(plate|layer|comp)", folder)
    if m:
        return {"comp": "composite"}.get(m.group(1), m.group(1)) + "_hdr"
    m = re.fullmatch(r"(hdr/)?upscale/[^/]+/out/(plate|layer|comp|matte)", folder)
    if m:
        part = {"comp": "composite"}.get(m.group(2), m.group(2))
        return "matte_upscaled" if part == "matte" else f"{part}{'_hdr' if m.group(1) else ''}_upscaled"
    return None


def frames(paths):
    """Each frame of a row in floats: the frames of a folder, or every frame of one movie at 16 bits per channel."""
    if len(paths) == 1 and os.path.splitext(paths[0])[1].lower() in plateio.VIDEO_EXTS:
        import av
        with av.open(paths[0]) as c:
            return [f.to_ndarray(format="rgb48le").astype(np.float32) / 65535.0 for f in c.decode(video=0)]
    return [plateio.read_float(p)[..., :3] for p in sorted(paths)]


def main():
    ap = argparse.ArgumentParser(description="The largest difference between the frames Finish's ComfyUI graph wrote and the page's own")
    ap.add_argument("--zip", help="the export's zip (default: the newest zip in ~/Downloads that holds Finish's graph)")
    ap.add_argument("--output", default="/data/ComfyUI/output", help="ComfyUI's output folder, where Finish's graph wrote")
    a = ap.parse_args()
    path = os.path.expanduser(a.zip) if a.zip else newest_zip("~/Downloads")
    print(f"Zip: {path}")
    worst = 0.0
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        api = finish_graph(z)
        if not api:
            sys.exit("This zip holds no Finish's graph.")
        names = z.namelist()
        compared = 0
        for n in api.values():
            if n["class_type"] not in SAVES or not isinstance(n["inputs"].get("filename_prefix"), str):
                continue
            prefix = n["inputs"]["filename_prefix"]
            folder = prefix if n["class_type"] == "PaintAPlate_SavePlate" else os.path.dirname(prefix)  # Save Frames: a folder, then a name
            rel = re.sub(r"^paintaplate/[^/]+/graph/", "", folder)
            row = row_of(rel)
            mine = [m for m in names if m.startswith(f"{row}/") or re.fullmatch(rf"[^/]+_{row}\.\w+", m)] if row else []
            if not mine:
                continue
            for m in mine:
                z.extract(m, tmp)
            made = [p for p in glob.glob(os.path.join(a.output, folder, "*")) if os.path.isfile(p)]
            if not made:
                print(f"{row}: the graph wrote nothing in {os.path.join(a.output, folder)}: run Finish's graph first")
                worst = float("inf")
                continue
            page, graph = frames([os.path.join(tmp, m) for m in mine]), frames(made)
            if len(page) != len(graph) or any(p.shape != g.shape for p, g in zip(page, graph)):
                print(f"{row}: {len(graph)} frames from the graph, {len(page)} from the page, of sizes {graph[0].shape[:2]} and {page[0].shape[:2]}")
                worst = float("inf")
                continue
            diffs = [float(np.max(np.abs(p - g))) for p, g in zip(page, graph)]
            at = int(np.argmax(diffs))
            print(f"{row}: {len(page)} frames, the largest difference {diffs[at]:.6f} at frame {at + 1}")
            worst, compared = max(worst, diffs[at]), compared + 1
    if not compared:
        sys.exit("No result of Finish's steps in this zip to compare: tick its stage (HDR, Upscaled) in Export.")
    print(f"LARGEST DIFFERENCE {worst:.6f}" + (": identical" if worst == 0 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
