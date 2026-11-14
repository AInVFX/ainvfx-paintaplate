"""The page workstream's check of a scene's graph in ComfyUI's own editor, on Adrien's laptop. Nothing is queued.

    python tests/graph_live.py --url http://127.0.0.1:8188 --graph <scene.comfyui.json> --out ~/paintaplate_gpu/graph_live

Google Chrome opens ComfyUI's editor and loads the file with app.loadGraphData, as a drop would. Then it checks:
1. every node's class is one this ComfyUI knows, else the editor draws the node red;
2. no node stands over another, at the sizes ComfyUI drew once the images loaded;
3. app.graphToPrompt() gives back, value for value, the API graph that the page saved in the same file
   (extra.paintaplate.prompt, written by graph.editorGraph). An input that only the editor holds is listed apart: an
   optional input that the page leaves out, at its default.
4. each image loader reads a file at the top of ComfyUI's input folder, and the README note names that file.
It measures the layout too: the canvas, and the links longer than 1500 px, each from its output slot to its input slot.
It writes graph_live.png (the whole graph on the canvas) and graph_live.json (every finding), and ends with 0 when 1 to 4
hold. PLAYWRIGHT_CHANNEL picks the browser (default: chrome).

    python tests/graph_live.py --offline --graph <scene.comfyui.json>

--offline needs no ComfyUI and no browser: the classes come from tests/js/object_info.scene.json, the sizes are the
saved ones, and check 3, which needs the editor, is left out."""
import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request

FRONTEND_ONLY = {"MarkdownNote", "Note", "Reroute", "PrimitiveNode"}  # nodes the editor draws with no class in /object_info
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js", "object_info.scene.json")  # --offline: the laptop's copy
TITLE, SLOT, LONG = 30, 20, 1500  # px: LiteGraph's title bar and slot row; a link longer than LONG crosses most of a screen
LOADERS = ("LoadImage", "LoadImageMask")
APP = "(window.app ?? window.comfyAPI?.app?.app)"
BOXES = f"""() => {{ const a = {APP}, t = window.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
  return (a.graph._nodes ?? a.graph.nodes).map((n) => [String(n.id), n.title, n.pos[0], n.pos[1] - t, n.size[0], n.size[1] + t]); }}"""
FIT = f"""async () => {{ try {{ await {APP}.extensionManager.command.execute("Comfy.Canvas.FitView"); return true; }} catch (e) {{ return false; }} }}"""


def link(v):
    """A link as the API writes it, ["12", 0], whatever the type of the node's id."""
    ok = isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)) and not isinstance(v[0], bool) and type(v[1]) is int
    return [str(v[0]), v[1]] if ok else v


def same(a, b):
    """Two input values: equal, a float within rounding, or a link whatever the type of its id."""
    if isinstance(a, float) or isinstance(b, float):
        return all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)) and math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
    return link(a) == link(b)


def differences(api, made):
    """The page's API graph against the editor's, node by node. Returns (wrong, added): wrong lists a node, a class or a
    value that differs; added lists the inputs that only the editor holds."""
    api, made = {str(k): v for k, v in api.items()}, {str(k): v for k, v in made.items()}
    wrong, added = [], []
    for nid in sorted(set(api) | set(made), key=lambda k: (len(k), k)):
        a, b = api.get(nid), made.get(nid)
        if a is None or b is None:
            wrong.append(f"{nid} {(a or b)['class_type']}: only in the {'editor' if a is None else 'page'}'s graph")
        elif a["class_type"] != b["class_type"]:
            wrong.append(f"{nid}: {a['class_type']} in the page's graph, {b['class_type']} in the editor's")
        else:
            for k in sorted(set(a["inputs"]) | set(b["inputs"])):
                if k not in b["inputs"]:
                    wrong.append(f"{nid} {a['class_type']}.{k}: {a['inputs'][k]!r} is missing from the editor's graph")
                elif k not in a["inputs"]:
                    added.append(f"{nid} {b['class_type']}.{k} = {b['inputs'][k]!r}")
                elif not same(a["inputs"][k], b["inputs"][k]):
                    wrong.append(f"{nid} {a['class_type']}.{k}: {a['inputs'][k]!r} became {b['inputs'][k]!r}")
    return wrong, added


def overlaps(boxes):
    """The pairs of nodes that stand over each other. A box is (id, title, x, y, width, height), its title bar included."""
    return [f"{a[0]} « {a[1]} » and {b[0]} « {b[1]} »" for i, a in enumerate(boxes) for b in boxes[i + 1:]
            if a[2] < b[2] + b[4] and b[2] < a[2] + a[4] and a[3] < b[3] + b[5] and b[3] < a[3] + a[5]]


def red(types, known):
    """The classes the editor draws red: unknown to this ComfyUI, and not drawn by the editor alone."""
    return sorted({t for t in types if t not in known and t not in FRONTEND_ONLY})


def spread(boxes, links):
    """The layout's measures: the canvas over every node, title bars included, and the links longer than LONG, each from
    its output slot on the right edge to its input slot on the left edge. A link is [id, origin, slot, target, slot, type]."""
    at, lengths = {str(b[0]): b for b in boxes}, []
    for _, origin, out, target, slot, *_ in links:
        a, b = at.get(str(origin)), at.get(str(target))
        if a and b:
            lengths.append(math.hypot(b[2] - (a[2] + a[4]), (b[3] + slot * SLOT) - (a[3] + out * SLOT)))
    width = max(b[2] + b[4] for b in boxes) - min(b[2] for b in boxes)
    height = max(b[3] + b[5] for b in boxes) - min(b[3] for b in boxes)
    return {"canvas": [round(width), round(height)], "links": len(lengths), "long": sum(v > LONG for v in lengths), "longest": round(max(lengths, default=0))}


def loaders(graph):
    """The image loaders' files: those in a subfolder, which ComfyUI's loaders do not list, and those the README note does
    not name."""
    files = [n["widgets_values"][0] for n in graph["nodes"] if n["type"] in LOADERS and n.get("widgets_values")]
    note = " ".join(str(v) for n in graph["nodes"] if n["type"] == "MarkdownNote" for v in n.get("widgets_values") or [])
    named = {w.strip(",.;:()«»\"'") for w in note.split()}
    return [f for f in files if "/" in f or "\\" in f], [f for f in files if f not in named]


def known_classes(url, types):
    """The classes of `types` that this ComfyUI knows, one /object_info/<class> each."""
    found = set()
    for t in sorted(set(types) - FRONTEND_ONLY):
        with urllib.request.urlopen(f"{url}/object_info/{urllib.parse.quote(t)}", timeout=30) as r:
            if t in json.load(r):
                found.add(t)
    return found


def in_editor(a, graph, out):
    """The graph in ComfyUI's editor, loaded as a drop would: the boxes ComfyUI drew, its API graph, and graph_live.png."""
    from playwright.sync_api import sync_playwright  # here, so that the unit tests need no browser
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome"), headless=not a.headed)
        page = browser.new_page(viewport={"width": 2560, "height": 1440})
        page.goto(a.url)
        page.wait_for_function(f"() => !!{APP}?.graph", timeout=120000)
        page.evaluate(f"async (g) => {{ await {APP}.loadGraphData(g); }}", graph)
        page.wait_for_timeout(4000)  # LoadImage shows its image, and the nodes take the size ComfyUI draws
        boxes = page.evaluate(BOXES)
        made = page.evaluate(f"async () => (await {APP}.graphToPrompt()).output")
        if not page.evaluate(FIT):
            page.keyboard.press(".")  # ComfyUI's key to fit the view
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(out, "graph_live.png"))
        browser.close()
    return boxes, made


def main():
    ap = argparse.ArgumentParser(description="A scene's graph in ComfyUI's own editor: red nodes, nodes over another, values against the page's API graph, image files, the layout")
    ap.add_argument("--url", default="http://127.0.0.1:8188", help="ComfyUI")
    ap.add_argument("--graph", required=True, help="a graph the page saved: a GPU case's scene.comfyui.json, or File > ComfyUI graph")
    ap.add_argument("--out", default=".", help="where graph_live.png and graph_live.json go")
    ap.add_argument("--headed", action="store_true", help="show the browser's window")
    ap.add_argument("--offline", action="store_true", help="no ComfyUI and no browser: classes from tests/js/object_info.scene.json, sizes as saved, no check 3")
    a = ap.parse_args()
    with open(os.path.expanduser(a.graph)) as f:
        graph = json.load(f)
    api = ((graph.get("extra") or {}).get("paintaplate") or {}).get("prompt")
    if not api:
        sys.exit("This file holds no API graph (extra.paintaplate.prompt): save the scene's graph again with a page from feat/page-w5 or later.")
    types = [n["type"] for n in graph["nodes"]]
    out = os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    if a.offline:
        with open(FIXTURE) as f:
            known = set(json.load(f)["nodes"])
        boxes = [[str(n["id"]), n.get("title") or n["type"], n["pos"][0], n["pos"][1] - TITLE, n["size"][0], n["size"][1] + TITLE] for n in graph["nodes"]]
        wrong, added = [], []
    else:
        known = known_classes(a.url, types)
        boxes, made = in_editor(a, graph, out)
        wrong, added = differences(api, made)
    deep, unnamed = loaders(graph)
    found = {"graph": a.graph, "offline": a.offline, "nodes": len(types), "red": red(types, known), "over": overlaps(boxes), "wrong": wrong,
             "added": added, "deep": deep, "unnamed": unnamed, "spread": spread(boxes, graph["links"])}
    with open(os.path.join(out, "graph_live.json"), "w") as f:
        json.dump(found, f, indent=1, ensure_ascii=False)
    sizes = "saved in the file" if a.offline else "ComfyUI drew"
    for key, what in (("red", "classes this ComfyUI does not know: the editor draws them red"), ("over", f"pairs of nodes over each other, at the sizes {sizes}"),
                      ("wrong", "differences from the page's API graph"), ("added", "inputs that only the editor holds: optional, at their default"),
                      ("deep", "image files in a subfolder: ComfyUI's loaders list only the top of the input folder"), ("unnamed", "image files the README note does not name")):
        print(f"{len(found[key])} {what}")
        for line in found[key][:40]:
            print(f"  {line}")
    s = found["spread"]
    print(f"Layout: canvas {s['canvas'][0]} x {s['canvas'][1]} px; {s['long']} of {s['links']} links longer than {LONG} px; the longest {s['longest']} px")
    if a.offline:
        print("Check 3, the values against the page's API graph, needs ComfyUI's editor: run it without --offline")
    ok = not (found["red"] or found["over"] or found["wrong"] or found["deep"] or found["unnamed"])
    print("GRAPH LIVE PASSED" if ok else "GRAPH LIVE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
