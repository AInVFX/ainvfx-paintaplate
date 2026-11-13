"""The page workstream's copy of what a running ComfyUI's /object_info says about the node classes of a scene's graph:
tests/js/object_info.scene.json, which graph.editorGraph's Node tests and the mock ComfyUI read. Nothing is queued.

    python tests/object_info_fixture.py --url http://127.0.0.1:8188

The classes are those already in the file, those of the workflows a scene's graph is made of (web/workflows: edit, matte,
clean, cleanup, shot, export, hdr), and those of any graph given with --graph. Each keeps the fields editorGraph reads:
every input in order, with its type and five of its options, and the outputs. A combo's choices are left out. A class
that this ComfyUI does not have keeps its entry, and the script names it."""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "js", "object_info.scene.json")
SCENE = ("edit", "matte", "clean", "cleanup", "shot", "export", "hdr")  # the workflows graph.sceneGraph puts in a scene
KEEP = ("default", "forceInput", "control_after_generate", "image_upload", "multiline")
FRONTEND_ONLY = {"MarkdownNote", "Note", "Reroute", "PrimitiveNode"}  # drawn by the editor, with no class in /object_info


def typed(spec):
    """One input: its type ("COMBO" for a list of choices) and the options editorGraph reads."""
    kind, opts = spec[0], spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    return ["COMBO" if isinstance(kind, list) else kind, {k: opts[k] for k in KEEP if k in opts}]


def entry(info):
    """A class as the file keeps it: its inputs in ComfyUI's order (input_order, when /object_info gives it) and its outputs."""
    inputs, order = {}, info.get("input_order") or {}
    for part in ("required", "optional"):
        spec = (info.get("input") or {}).get(part) or {}
        names = [n for n in order.get(part, []) if n in spec]
        names += [n for n in spec if n not in names]
        if names:
            inputs[part] = {n: typed(spec[n]) for n in names}
    return {"input": inputs, "output": list(info.get("output") or []), "output_name": list(info.get("output_name") or [])}


def classes(graph):
    """The node classes of a graph, in the editor's format (nodes) or the API's (class_type)."""
    if isinstance(graph.get("nodes"), list):
        return {n["type"] for n in graph["nodes"]}
    return {v["class_type"] for v in graph.values() if isinstance(v, dict) and "class_type" in v}


def main():
    ap = argparse.ArgumentParser(description="Write tests/js/object_info.scene.json from a running ComfyUI's /object_info")
    ap.add_argument("--url", default="http://127.0.0.1:8188", help="ComfyUI")
    ap.add_argument("--graph", action="append", default=[], help="a saved graph whose classes join the file; give it again for more")
    ap.add_argument("--out", default=FILE, help="the file to write (default: the fixture itself)")
    a = ap.parse_args()

    def get(path):
        with urllib.request.urlopen(f"{a.url}{path}", timeout=60) as r:
            return json.load(r)

    with open(FILE) as f:
        old = json.load(f)["nodes"]
    wanted = set(old)
    for path in [os.path.join(HERE, "..", "web", "workflows", f"{n}.json") for n in SCENE] + [os.path.expanduser(g) for g in a.graph]:
        with open(path) as f:
            wanted |= classes(json.load(f))
    nodes, missing = {}, []
    for cls in sorted(wanted - FRONTEND_ONLY):
        info = get(f"/object_info/{urllib.parse.quote(cls)}").get(cls)
        if info:
            nodes[cls] = entry(info)
        else:
            missing.append(cls)
            if cls in old:
                nodes[cls] = old[cls]
    version = (get("/system_stats").get("system") or {}).get("comfyui_version") or "of unknown version"
    when = datetime.now(ZoneInfo("America/Toronto")).strftime("%-d %B %Y")
    about = ("What ComfyUI's /object_info says about the node classes of a scene's graph (with and without SDR to HDR), in the fields "
             "graph.editorGraph reads: each input in order with its type and five of its options (default, forceInput, "
             "control_after_generate, image_upload, multiline), and the outputs. A combo's choices are left out. "
             f"Read from a running ComfyUI {version} at {a.url} on {when} (Toronto), by tests/object_info_fixture.py.")
    if missing:
        about += f" Not in that ComfyUI, kept as they were: {', '.join(missing)}."
    with open(a.out, "w") as f:
        json.dump({"about": about, "nodes": nodes}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"{len(nodes)} classes written to {a.out}" + (f"; not in this ComfyUI, kept as they were: {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
