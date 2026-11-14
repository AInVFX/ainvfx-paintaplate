"""Asks for the page's first-frame erase in several ways on a running ComfyUI, and says which way removes the object.

    python tests/erase_probe.py plates/horse.mp4 --out ~/paintaplate_gpu/erase_probe
        [--url http://127.0.0.1:8188] [--seed 1017942128] [--stroke NAME:x,y;x,y;...[:SIZE[:WORDS]]] [--full]
        [--requests page,wide,dimmed,crop,named,as_words,own]

`plate` is the path the page sends, under ComfyUI's input folder: the probe opens it with the page's own `ingest`, and draws
every image and mask as the page's canvas does (bilinear, sampled at each pixel's centre). Run it in the tests' environment: the page's rules come from web/logic.mjs itself, run by Node, and
Playwright's own Node serves when no other is on the PATH.

For each stroke, the probe does what the page does for an erase with Whole object on (prepare, writeCaption and generate in
web/app.mjs), with the page's own workflows (snap, prompt and edit in tools/build_workflows.py), and asks for Klein's caption
in each way of REQUESTS. When the writer's answer to the page's request removes another object, for a stroke with no
words, the probe goes on as the page does (prepare and leaveOut in web/app.mjs): SAM 3.1 finds that object by the writer's
name for it, the writer's box leaves it out (logic.boxWithout), and the writer is asked once more. Klein then runs its quick pass, the page's first look, once per mask and caption that differ;
--full adds the page's full-size pass. With no --stroke: three strokes on horse.mp4 with no words, the barn of the GPU case
horse_erase, the fence post under it and the tree above it. The jobs are grouped by model, so that each model loads few
times on a 16 GB card: SAM 3.1 at every stroke's points, the writer's name for every object, SAM 3.1 by that name, the
writer for every request, Klein for every caption, then SAM 3.1 on every result.

Each result is measured inside the mask Klein got, at the quick pass's size:
- changed: the page's rule (logic.erasedShare), the share of the object whose 4-pixel cells moved by more than 12 levels
  of 255 (under 2%, the page says that the object stayed), then the same at 24 and at 48 levels;
- edges: the correlation of the gradient's size before and after (1: the same edges; near 0: none of them);
- SAM again: SAM 3.1 at the stroke's points on the result, and the intersection over union of what it keeps with the object
  it kept on the frame (near 1: the object is still there; 0: SAM finds nothing there).

It writes to --out: report.md (one row per stroke and request, then every answer in full), sheet.png (the frame around each
object, then the result of each request), answers.json (all of it, for a script), and the images it sent and got back.
ComfyUI keeps its own copies under output/paintaplate/erase_probe_<time>: delete them freely.
"""
import argparse
import base64
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(REPO, "tools")]
from build_workflows import fill, outputs_of  # noqa: E402
from comfy_live import http, submit, wait  # noqa: E402

# web/app.mjs: the long sides of the full size and of the quick pass, Klein's two passes, the mask's growth (the width over
# EDIT_GROW) and the paint's grid (cells across). tests/test_erase_probe.py keeps them equal to the page's.
WORK_SIDE, EDIT_SIDE = 1920, 768
QUICK = {"steps": 16, "denoise": 1, "feather": 6, "sigma": 3}
FULL = {"steps": 8, "denoise": 0.35, "feather": 12, "sigma": 6}
EDIT_GROW, PAINT_GRID = 48, 96
SNAP_STEP = 8  # work pixels between two points that the page records along a drag (about)
DIM = 0.3  # what the dimmed frame keeps of the light outside the object
LEVELS = (12, 24, 48)  # the page's rule, then two stricter ones
CASE = "horse_erase"  # tests/gpu_matrix.json: the barn's stroke
NAME_SYSTEM = ("You see an image in which one object keeps its full colour and everything else is dimmed. Name that object: "
               "answer with its common name only, in one to three words, with no article and no sentence.")
NAME_REQUEST = "Name the object that keeps its full colour."
REQUESTS = {  # how each one asks for Klein's caption: what the prompt writer sees, and the boxes it gets
    "page": "the page's own request (logic.writerBoxes): with no words and one painted part, one box cut to the stroke and to "
            "what most of SAM's masks hold (logic.coreBox); otherwise one box per painted part. An answer about another "
            "object: that object left out of the box (logic.boxWithout), and the writer asked once more",
    "wide": "the request before 1.11.14: one box per painted part, around SAM's whole union (logic.paintBoxes)",
    "dimmed": "the page's request, on the frame with all but the object dimmed to 30% of its light",
    "crop": "the page's request on the object's own crop (its box, and half its size on each side); "
            "the boxes of the answer come back to the frame",
    "named": "a first question names the object, on the dimmed frame; the page's own caption then carries that name",
    "as_words": "the same name, then the page as if it had been typed: SAM 3.1 by name, the locked boxes of its mask, "
                "the writer's request with the name, and Klein inside that mask",
    "own": "the page's own caption, with no prompt writer: what the page sends when it refuses the writer's answer",
}


def default_strokes():
    with open(os.path.join(HERE, "gpu_matrix.json")) as f:
        _, words, points, size, _ = json.load(f)[CASE]["strokes"][0]
    return [{"name": "barn", "words": words, "points": points, "size": size},
            {"name": "post", "words": "", "points": [[0.938, 0.56], [0.938, 0.64], [0.938, 0.72], [0.938, 0.8]], "size": 36},
            {"name": "tree", "words": "", "points": [[0.79, 0.26], [0.83, 0.25], [0.87, 0.27]], "size": 36}]


def parse_stroke(text):
    """NAME:x,y;x,y;...[:SIZE[:WORDS]]: points as fractions of the frame's width and height, SIZE in full-size pixels."""
    name, points, *rest = text.split(":")
    pts = [[float(v) for v in p.split(",")] for p in points.split(";") if p.strip()]
    return {"name": name, "points": pts, "size": float(rest[0]) if rest and rest[0] else 36, "words": ":".join(rest[1:])}


def jround(v):  # JavaScript's Math.round: a half goes up
    return int(np.floor(v + 0.5))


# ---------- The page's rules, from web/logic.mjs ----------

BRIDGE = """
import * as L from %s;
const take = (v) => (Array.isArray(v) ? v.map(take) : v && typeof v === "object"
  ? ("$b64" in v ? new Uint8Array(Buffer.from(v.$b64, "base64")) : Object.fromEntries(Object.entries(v).map(([k, x]) => [k, take(x)])))
  : v);
let input = "";
process.stdin.on("data", (d) => (input += d));
const give = (k, v) => (v instanceof Uint8Array ? { $b64: Buffer.from(v).toString("base64") } : v);
process.stdin.on("end", () => process.stdout.write(JSON.stringify(JSON.parse(input).map(([fn, ...args]) => {
  const a = args.map(take), r = L[fn](...a);
  if (fn !== "pickObjects") return r;
  return r.map((m) => (a[0].named.includes(m) ? ["named", a[0].named.indexOf(m)] : ["points", a[0].points.indexOf(m)]));
}), give)));
"""
NODE = []


def node():
    found = shutil.which("node")
    if not found:
        try:
            import playwright
            found = os.path.join(os.path.dirname(playwright.__file__), "driver", "node")
        except ImportError:
            found = None
    if not found or not os.path.exists(found):
        sys.exit("The probe runs the page's rules (web/logic.mjs) with Node: install Node, or run the probe in the tests' "
                 "environment, whose Playwright brings its own.")
    return found


def page(*calls):
    """web/logic.mjs's own functions, run by Node: page(("fitSize", 1920, 1080, 768, 16), ...) gives [result, ...].
    Bytes go as raw(...) and arrive as Uint8Arrays, and a Uint8Array comes back as bytes; for pickObjects, the answer says
    which masks it kept."""
    if not NODE:
        NODE.append(node())
    uri = pathlib.Path(REPO, "web", "logic.mjs").as_uri()
    done = subprocess.run([NODE[0], "--input-type=module", "-e", BRIDGE % json.dumps(uri)], input=json.dumps(calls),
                          capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"web/logic.mjs: {done.stderr.strip()[-2000:]}")
    return [np.frombuffer(base64.b64decode(r["$b64"]), np.uint8) if isinstance(r, dict) and "$b64" in r else r
            for r in json.loads(done.stdout)]


def raw(a):
    return {"$b64": base64.b64encode(np.ascontiguousarray(a, np.uint8).tobytes()).decode()}


# ---------- Images, as the page's canvases make them ----------

def resized(img, size):
    """An image (H x W [x C], 8 bits) drawn at `size` (width, height) as the page's canvas draws it: bilinear, sampled at each
    new pixel's centre, with no average over a wider area. An average (Pillow's resize) grew the barn's grid by a row on top,
    and the probe asked with [343, 721, 490, 1000] where the page asked with [362, 721, 490, 1000] (12 and 13 Nov 2026)."""
    h, w = img.shape[:2]
    W, H = size
    if (w, h) == (W, H):
        return img
    ys, xs = np.clip((np.arange(H) + 0.5) * h / H - 0.5, 0, h - 1), np.clip((np.arange(W) + 0.5) * w / W - 0.5, 0, w - 1)
    y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
    y1, x1 = np.minimum(y0 + 1, h - 1), np.minimum(x0 + 1, w - 1)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    if img.ndim == 3:
        fy, fx = fy[..., None], fx[..., None]
    a = img.astype(np.float32)
    top, bottom = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx, a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    return np.clip(top * (1 - fy) + bottom * fy + 0.5, 0, 255).astype(np.uint8)


def mask_at(mask, size):  # app.maskAt: the mask at `size`, as 0 and 1
    return resized(mask.astype(np.uint8) * 255, size) > 127


def rgba(img):
    return np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])


def white(mask):  # a mask as the page uploads it: white on black
    return np.repeat((mask.astype(np.uint8) * 255)[..., None], 3, 2)


def over(base, patch):
    """`patch` (RGBA) drawn over `base` (RGB) at the base's size, as the page draws a patch on a canvas."""
    h, w = base.shape[:2]
    p = (patch if patch.shape[:2] == (h, w) else resized(patch, (w, h))).astype(np.float32)
    a = p[..., 3:4] / 255
    return np.clip(p[..., :3] * a + base * (1 - a) + 0.5, 0, 255).astype(np.uint8)


def stroke_mask(stroke, work):
    """The stroke as the page paints it at the full size: a round brush, `size` pixels across, along its points."""
    w, h = work
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    pts = [(x * w, y * h) for x, y in stroke["points"]]
    r = stroke["size"] / 2
    if len(pts) > 1:
        d.line(pts, fill=255, width=max(1, jround(stroke["size"])), joint="curve")
    for x, y in pts:
        d.ellipse((x - r, y - r, x + r, y + r), fill=255)
    return np.asarray(img) > 127


def snap_points(stroke, work, prev):
    """app.findWhole: up to five points along the stroke, one SAM prompt each, at the quick pass's size."""
    w, h = work
    corners = [np.array((x * w, y * h)) for x, y in stroke["points"]]
    pts = corners[:1]
    for a, b in zip(corners, corners[1:]):
        n = max(1, int(np.hypot(*(b - a)) // SNAP_STEP))
        pts += [a + (b - a) * (i / n) for i in range(1, n + 1)]
    picks = list(dict.fromkeys(jround(f * (len(pts) - 1)) for f in (0, 0.25, 0.5, 0.75, 1)))
    k = prev[0] / w
    return {f"point_{j}": json.dumps([{"x": jround(pts[i][0] * k), "y": jround(pts[i][1] * k)}], separators=(",", ":"))
            for j, i in enumerate(picks)}


def bounds(mask):
    """canvas.bounds: the mask's box as [y_min, x_min, y_max, x_max] on 0..1000, read at 256 cells across."""
    h, w = mask.shape
    small = resized(mask.astype(np.uint8) * 255, (256, max(1, jround(256 * h / w)))) >= 16
    return tight_box(small) or [0, 0, 1000, 1000]


def tight_box(mask):
    """A mask's box on 0..1000 at its own resolution, with no margin; None when it is empty."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    h, w = mask.shape
    return [jround(v * 1000) for v in (ys.min() / h, xs.min() / w, (ys.max() + 1) / h, (xs.max() + 1) / w)]


def paint_grid(mask):
    """app.paintGrid: the painted area on PAINT_GRID cells across, as logic.paintBoxes and erasesPaint take it."""
    h, w = mask.shape
    gh = max(1, jround(PAINT_GRID * h / w))
    return {"bits": raw(resized(mask.astype(np.uint8) * 255, (PAINT_GRID, gh)).ravel() > 32), "w": PAINT_GRID, "h": gh}


def crop_of(bbox):
    """The object's own crop for the writer, on 0..1000: its box, and half its size on each side, inside the frame."""
    y0, x0, y1, x1 = bbox
    dy, dx = (y1 - y0) / 2, (x1 - x0) / 2
    return [max(0, jround(y0 - dy)), max(0, jround(x0 - dx)), min(1000, jround(y1 + dy)), min(1000, jround(x1 + dx))]


def crop_image(frame, crop):
    """The frame cut to `crop`, at the quick pass's long side."""
    H, W = frame.shape[:2]
    y0, x0 = jround(crop[0] * H / 1000), jround(crop[1] * W / 1000)
    part = frame[y0:max(y0 + 1, jround(crop[2] * H / 1000)), x0:max(x0 + 1, jround(crop[3] * W / 1000))]
    k = EDIT_SIDE / max(part.shape[:2])
    return resized(part, (max(1, jround(part.shape[1] * k)), max(1, jround(part.shape[0] * k))))


def to_crop(box, crop):
    """A box on the frame's 0..1000, on the crop's own 0..1000, cut to the crop."""
    y0, x0, y1, x1 = crop
    sy, sx = (y1 - y0) / 1000, (x1 - x0) / 1000
    return [min(1000, max(0, jround((v - o) / s))) for v, o, s in zip(box, (y0, x0, y0, x0), (sy, sx, sy, sx))]


def to_frame(box, crop):
    """A box on the crop's 0..1000, back on the frame's."""
    y0, x0, y1, x1 = crop
    sy, sx = (y1 - y0) / 1000, (x1 - x0) / 1000
    return [jround(o + v * s) for v, o, s in zip(box, (y0, x0, y0, x0), (sy, sx, sy, sx))]


def rows_to_frame(rows, crop):
    """The rows of an answer written on the crop, with their boxes on the frame."""
    def box(b):
        return to_frame(b, crop) if isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b) else b
    return [{k: box(v) if k in ("bbox", "src_bbox", "tgt_bbox") else v for k, v in r.items()} if isinstance(r, dict) else r
            for r in rows]


def name_of(text):
    """The object's name in the writer's answer: its first line, without quotes, article or full stop; four words at most."""
    lines = [t for t in (text or "").strip().splitlines() if t.strip()]
    words = re.sub(r"[^\w\s-]", " ", lines[0]).split() if lines else []
    while words and words[0].lower() in ("the", "a", "an"):
        words.pop(0)
    return " ".join(words[:4]).lower()


# ---------- Measures ----------

def shares(after, before, mask):
    """logic.erasedShare at each of LEVELS."""
    h, w = mask.shape
    arrays = [raw(rgba(after)), raw(rgba(before)), raw(rgba(white(mask)))]
    return page(*[("erasedShare", *arrays, w, h, {"levels": n}) for n in LEVELS])


def check(after, before, mask):
    """logic.eraseCheck: what the page says of the erase, left or not, with its two measures (changed at 24 levels, edges)."""
    h, w = mask.shape
    return page(("eraseCheck", raw(rgba(after)), raw(rgba(before)), raw(rgba(white(mask))), w, h))[0]


def overlap(a, b):
    return float((a & b).sum() / max(1, (a | b).sum()))


# ---------- ComfyUI ----------

def about(url):
    try:
        stats, _ = http(f"{url}/system_stats", timeout=10)
    except Exception as err:  # noqa: BLE001
        sys.exit(f"No ComfyUI answers at {url}: {err}")
    device = (stats.get("devices") or [{}])[0]
    said = f"ComfyUI {stats.get('system', {}).get('comfyui_version', '(version unknown)')} on {device.get('name', 'its GPU')}"
    try:
        version, _ = http(f"{url}/paintaplate/version", timeout=10)
        said += f", Paint a plate {version.get('version', '') if isinstance(version, dict) else version}"
    except Exception:  # noqa: BLE001
        pass
    return said


def upload(url, img, name, folder):
    """One image to ComfyUI's input folder, kept in `folder` too; the name that Load Image takes."""
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "PNG")
    with open(os.path.join(folder, name), "wb") as f:
        f.write(buf.getvalue())
    res, _ = http(f"{url}/upload/image", {"overwrite": "true"}, {"image": (name, buf.getvalue())})
    return f"{res['subfolder']}/{res['name']}" if res.get("subfolder") else res["name"]


def run(url, name, values, limit):
    """One of the page's workflows, filled as the page fills it: ({output: what it gave}, seconds)."""
    prompt = fill(name, values)
    pid = submit(url, prompt)["prompt_id"]
    entry, seconds = wait(url, pid, limit)
    if entry is None:
        raise RuntimeError(f"{name}: no answer in {limit:.0f} s")
    status = entry.get("status", {})
    if status.get("status_str") == "error":
        said = [m[1] for m in status.get("messages", []) if m[0] == "execution_error"]
        raise RuntimeError(f"{name}: {said[0].get('exception_message', said[0]) if said else 'it failed'}")
    return {out: entry.get("outputs", {}).get(nid, {}) for out, nid in outputs_of(prompt).items()}, seconds


def text_of(got):
    return ((got.get("text", {}).get("text") or [""])[0] or "").strip()


def image(url, item, mode="RGB"):
    q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                "type": item.get("type", "output")})
    with urllib.request.urlopen(f"{url}/view?{q}", timeout=300) as r:
        return np.asarray(Image.open(io.BytesIO(r.read())).convert(mode))


def objects_of(url, got, painted, points, prev):
    """app.findWhole: SAM's masks at the quick pass's size, and those that logic.pickObjects keeps, as [(kind, mask)]."""
    def bits(item):
        m = image(url, item, "L")
        return (m if m.shape[::-1] == tuple(prev) else resized(m, prev)) > 127
    named = [bits(i) for i in got.get("named", {}).get("images", [])]
    pts = [bits(got[k]["images"][0]) for k in points if got.get(k, {}).get("images")]
    picked = page(("pickObjects", {"painted": raw(painted.ravel()), "points": [raw(m.ravel()) for m in pts],
                                    "named": [raw(m.ravel()) for m in named], "area": int(painted.size)}))[0]
    return [(kind, (named if kind == "named" else pts)[i]) for kind, i in picked]


def path_of(url, o, words, got, prev, work):
    """What the page prepares for an erase once SAM has answered, with these words (app.prepare): the object's masks, its
    box, the paint's grid and locked boxes, the page's own caption, and the tight box and the crop of two requests."""
    kept = objects_of(url, got, o["painted"], o["points"], prev)
    p = {"words": words, "kept": [kind for kind, _ in kept], "sam": np.zeros(prev[::-1], bool)}
    for _, m in kept:
        p["sam"] |= m
    p["mask_work"] = o["painted_work"] | (resized(p["sam"].astype(np.uint8) * 255, work) > 127)
    p["mask_prev"], p["bbox"], p["paint"] = mask_at(p["mask_work"], prev), bounds(p["mask_work"]), paint_grid(p["mask_work"])
    got = page(("caption", {"tool": "erase", "words": words, "colors": [], "color": "#ffffff", "bbox": p["bbox"]}),
               ("paintBoxes", p["paint"]),
               ("coreBox", {"painted": raw(o["painted"].ravel()), "masks": [raw(m.ravel()) for _, m in kept],
                            "w": int(prev[0]), "h": int(prev[1])}),
               ("corePixels", {"painted": raw(o["painted"].ravel()), "masks": [raw(m.ravel()) for _, m in kept],
                               "w": int(prev[0]), "h": int(prev[1])}))
    p["own"], p["parts"], p["core"] = got[0], got[1], got[2] if kept and not words.strip() else None  # app.findWhole
    p["core_bits"] = got[3].reshape(prev[::-1])
    p["chosen"] = page(("writerBoxes", {"tool": "erase", "words": words, "parts": p["parts"], "core": p["core"],
                                        "bbox": p["bbox"]}))[0]  # app.writeCaption
    p["crop"] = crop_of(p["bbox"])
    return p


def leave_out(url, frame_name, r, P, locked, prev, system, limit):
    """app.leaveOut, then app.writeCaption once more: SAM 3.1 finds the objects that the writer's answer removes by the
    writer's names for them, the writer's box leaves them out (logic.boxWithout), and the writer gets that box. A kept
    answer becomes the request's caption."""
    r["others"] = page(("removedNames", r["made"], locked))[0]
    if not r["others"]:
        return
    got, r["others_seconds"] = run(url, "snap", {"image": frame_name, "words": ", ".join(r["others"])}, limit)
    other = np.zeros(prev[::-1], bool)
    for item in got.get("named", {}).get("images", []):
        m = image(url, item, "L")
        other |= (m if m.shape[::-1] == tuple(prev) else resized(m, prev)) > 127
    r["cut"] = page(("boxWithout", {"box": P["core"], "keep": raw(P["core_bits"].ravel()), "other": raw(other.ravel()),
                                    "w": int(prev[0]), "h": int(prev[1])}))[0]
    if not r["cut"]:
        return
    chosen = page(("writerBoxes", {"tool": "erase", "words": "", "parts": P["parts"], "core": r["cut"], "bbox": P["bbox"]}))[0]
    ask = page(("upsampleRequest", {"tool": "erase", "words": "", **chosen}))[0]
    try:
        got, r["again_seconds"] = run(url, "prompt", {"image": frame_name, "request": ask["request"],
                                                      "system": system[ask["mode"]]}, limit)
        r["again"] = text_of(got)
    except Exception as err:  # noqa: BLE001
        r["again"], r["again_error"] = "", str(err)
    made = page(("reconcile", r["again"], ask["locked"]))[0] if r["again"] else ""
    r["again_refused"] = not made or not page(("erasesPaint", made, ask["locked"], P["paint"]))[0]
    if not r["again_refused"]:
        r["made"], r["refused"], r["caption"] = made, False, made


def edit_key(r):  # one Klein job per mask and caption
    return f"{r['path']}|{r['caption']}"


def first_frame(url, plate, tag, limit):
    """The plate's first frame as the page opens it: the hero frame of the page's own `ingest` (openPlate in web/app.mjs),
    with the values tests/open_probe.py sends for the page."""
    from open_probe import page_values
    try:
        st, _ = http(f"{url}/paintaplate/stat?{urllib.parse.urlencode({'path': plate, 'config': '', 'cs': ''})}")
        got, _ = run(url, "ingest", page_values(plate, st, f"paintaplate/{tag}"), limit)
    except Exception as err:  # noqa: BLE001
        sys.exit(f"ComfyUI could not open {plate}: {err}")
    return image(url, got["hero"]["images"][0])


# ---------- What it writes ----------

def pct(v):
    return "none" if v is None else f"{v * 100:.0f}%"


def num(v):
    return "none" if v is None else f"{v:.2f}"


def verdict(req, r):
    if req == "own":
        return "the page's own caption: no writer"
    if req == "named":
        return f"named « {r.get('name') or 'nothing'} »: the page's own caption with that name"
    head = f"named « {r.get('name') or 'nothing'} », then as typed: " if req == "as_words" else ""
    if r.get("error"):
        return f"{head}{r['error']}: the page's own caption"
    if not r.get("answer"):
        return f"{head}no answer: the page's own caption"
    if r.get("others"):  # the page's request, about another object: the box without it, and the writer once more
        first = f"named « {', '.join(r['others'])} » first, "
        if not r.get("cut"):
            return first + "no box without it: the page's own caption"
        return first + ("kept with the box without it: the writer's caption" if not r.get("refused")
                        else "refused again with the box without it: the page's own caption")
    return head + ("refused: the page's own caption" if r.get("refused") else "kept: the writer's caption")


def measured(e):
    if "share" not in e:
        return e.get("error", "no result")
    return (f"{' / '.join(pct(v) for v in e['share'])} · edges {num(e.get('edges'))} · SAM {num(e.get('sam'))}"
            f" · {'left' if e['check']['left'] else 'gone'}")


def short(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def view_box(bbox, prev):
    """Where the sheet looks: around the object's box, twice its size, 16:9, inside the frame (quick-pass pixels)."""
    pw, ph = prev
    y0, x0, y1, x1 = bbox[0] * ph / 1000, bbox[1] * pw / 1000, bbox[2] * ph / 1000, bbox[3] * pw / 1000
    w = min(pw, ph * 16 / 9, max(pw / 4, 2 * (x1 - x0), 2 * (y1 - y0) * 16 / 9))
    h = w * 9 / 16
    cx, cy = min(max((x0 + x1) / 2, w / 2), pw - w / 2), min(max((y0 + y1) / 2, h / 2), ph - h / 2)
    return (int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2))


def font_of(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before 10.1
        return ImageFont.load_default()


def sheet(path, objs, asked, frame_prev, title):
    """One row per stroke: the frame around the object (its mask's edge in red, the stroke in yellow, the locked boxes in
    cyan), then the result of each request, with what the writer said and the measures."""
    cw, ch, th, gap = 384, 216, 60, 8
    font = font_of(13)
    rows = [o for o in objs if "page" in o["paths"]]
    ph, pw = frame_prev.shape[:2]
    img = Image.new("RGB", (gap + (len(asked) + 1) * (cw + gap), 34 + max(1, len(rows)) * (ch + th + gap)), "white")
    d = ImageDraw.Draw(img)
    d.text((gap, 8), title, fill="black", font=font)
    for n, o in enumerate(rows):
        P = o["paths"]["page"]
        y, view, m = 34 + n * (ch + th + gap), view_box(P["bbox"], (pw, ph)), P["mask_prev"]
        marked = frame_prev.copy()
        marked[o["painted"]] = (marked[o["painted"]] * 0.5 + np.array([255, 220, 0]) * 0.5).astype(np.uint8)
        marked[(m ^ np.roll(m, 1, 0)) | (m ^ np.roll(m, 1, 1))] = (255, 40, 40)
        before = Image.fromarray(marked)
        for b in P["chosen"]["boxes"]:
            ImageDraw.Draw(before).rectangle((b[1] * pw / 1000, b[0] * ph / 1000, b[3] * pw / 1000, b[2] * ph / 1000),
                                             outline=(0, 220, 255))
        cells = [(before, [f"{o['name']}: the frame", f"SAM kept {len(P['kept'])} mask(s), box {P['bbox']}",
                           "red: the mask; cyan: the locked boxes"])]
        for req in asked:
            r = o["requests"].get(req)
            e, after = (o["edits"].get(edit_key(r), {}), o["afters"].get(edit_key(r))) if r else ({}, None)
            said = (r or {}).get("answer") if req not in ("own", "named") else (r or {}).get("caption")
            cells.append((after if after is None else Image.fromarray(after),
                          [short(f"{req}: {verdict(req, r or {})}", 54), f"« {short(said, 50)} »", short(measured(e), 54)]))
        for k, (im, text) in enumerate(cells):
            x = gap + k * (cw + gap)
            if im is not None:
                img.paste(im.crop(view).resize((cw, ch)), (x, y))
            for i, t in enumerate(text):
                d.text((x, y + ch + 3 + i * 18), t, fill="black", font=font)
    img.save(path)


def report(path, objs, asked, head):
    lines = list(head)
    for o in objs:
        s = o["stroke"]
        lines += ["", f"## {s['name']}", "", f"The stroke: {len(s['points'])} points from {s['points'][0]} to {s['points'][-1]}, "
                  f"{s['size']:g} pixels across, " + (f"with « {s['words']} »." if s["words"] else "with no words.")]
        if "error" in o:
            lines += ["", o["error"]]
            continue
        P, Q = o["paths"]["page"], o["paths"].get("name")
        lines += ["", f"SAM 3.1 kept {len(P['kept'])} mask(s) ({', '.join(P['kept']) or 'none'}). The object's box {P['bbox']}; "
                  f"the writer's boxes {P['chosen']['boxes']}; the boxes before 1.11.14 {P['parts']}; the crop {P['crop']}."]
        if "naming" in o:
            lines += ["", f"The writer names it « {o.get('object') or 'nothing'} » (its answer: « {short(o['naming'].get('answer'), 80)} »)."
                      + (f" SAM 3.1 by that name kept {len(Q['kept'])} mask(s) ({', '.join(Q['kept']) or 'none'}); the object's "
                         f"box {Q['bbox']}; the writer's boxes {Q['chosen']['boxes']}." if Q else f" {o.get('name_error', '')}".rstrip())]
        lines += ["", "| Request | The writer's answer | The page | Changed at 12 / 24 / 48 levels | Edges | SAM again | The page's check | Seconds |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for req in asked:
            r = o["requests"][req]
            e = o["edits"].get(edit_key(r), {})
            cells = [req, short(r.get("answer") or "", 110).replace("|", "/"), verdict(req, r),
                     " / ".join(pct(v) for v in e["share"]) if "share" in e else e.get("error", "no result"),
                     num(e.get("edges")), num(e.get("sam")), ("left" if e["check"]["left"] else "gone") if "check" in e else "",
                     f"{r.get('seconds', 0):.0f} + {e.get('quick_seconds', 0) + e.get('full_seconds', 0):.0f}"]
            lines.append("| " + " | ".join(cells) + " |")
        lines += ["", "In full:", ""]
        for req in asked:
            r = o["requests"][req]
            if r.get("answer"):
                lines += [f"- {req}, the writer's answer:", "", "  ```text", f"  {' '.join(r['answer'].split())}", "  ```", ""]
            lines += [f"- {req}, the caption Klein got:", "", "  ```text", f"  {' '.join(r['caption'].split())}", "  ```", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def plain(o):
    keep = ("name", "stroke", "points", "object", "naming", "name_error", "error", "requests", "edits")
    out = {k: o[k] for k in keep if k in o}
    out["paths"] = {k: {f: p[f] for f in ("words", "kept", "bbox", "parts", "core", "chosen", "crop", "own", "ask", "seconds") if f in p}
                    for k, p in o["paths"].items()}
    return out


# ---------- The probe ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plate", nargs="?", default="plates/horse.mp4")
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--out", help="the folder for the report (default: erase_probe_<time>, here)")
    ap.add_argument("--seed", type=int, default=1017942128)
    ap.add_argument("--stroke", action="append", help="NAME:x,y;x,y;...[:SIZE[:WORDS]], once per stroke")
    ap.add_argument("--requests", default=",".join(REQUESTS), help="which ways to ask, of: " + ", ".join(REQUESTS))
    ap.add_argument("--full", action="store_true", help="also the page's full-size pass, which the page's check measures")
    ap.add_argument("--limit", type=float, default=600, help="seconds that one job may take (default 600)")
    a = ap.parse_args(argv)
    asked = [r for r in a.requests.split(",") if r]
    if not asked or set(asked) - set(REQUESTS):
        sys.exit(f"--requests takes some of: {', '.join(REQUESTS)}")
    t0, stamp = time.time(), time.strftime("%Y%m%d_%H%M%S")
    tag, out = f"erase_probe_{stamp}", os.path.expanduser(a.out or f"erase_probe_{stamp}")
    sent, made = os.path.join(out, "sent"), os.path.join(out, "results")
    for folder in (sent, made):
        os.makedirs(folder, exist_ok=True)

    def say(text):
        print(f"{time.time() - t0:6.1f} s  {text}", flush=True)

    facts = about(a.url)
    frame = first_frame(a.url, a.plate, tag, a.limit)
    H, W = frame.shape[:2]
    work, prev = page(("fitSize", W, H, WORK_SIDE, 32), ("fitSize", W, H, EDIT_SIDE, 16))
    frame_prev, frame_work = resized(frame, prev), resized(frame, work)
    with open(os.path.join(REPO, "web", "upsampler.json")) as f:
        system = json.load(f)
    strokes = [parse_stroke(s) for s in a.stroke] if a.stroke else default_strokes()
    naming = bool({"named", "as_words"} & set(asked))
    say(f"{facts}. {a.plate}, {W} x {H}: the quick pass at {prev[0]} x {prev[1]}, the full size {work[0]} x {work[1]}. "
        f"{len(strokes)} stroke(s); requests: {', '.join(asked)}")
    frame_name = upload(a.url, frame_prev, f"{tag}_frame.png", sent)

    # 1. SAM 3.1 at the stroke's points: the whole object (app.prepare, findWhole)
    objs = []
    for s in strokes:
        o = {"name": s["name"], "stroke": s, "paths": {}, "requests": {}, "edits": {}, "afters": {}}
        objs.append(o)
        o["painted_work"] = stroke_mask(s, work)
        o["painted"], o["points"] = mask_at(o["painted_work"], prev), snap_points(s, work, prev)
        try:
            got, seconds = run(a.url, "snap", {"image": frame_name, "words": s["words"], **o["points"]}, a.limit)
            P = o["paths"]["page"] = path_of(a.url, o, s["words"], got, prev, work)
        except Exception as err:  # noqa: BLE001
            o["error"] = f"SAM 3.1 failed: {err}"
            say(f"{s['name']}: {o['error']}")
            continue
        P["seconds"] = seconds
        say(f"{s['name']}: SAM 3.1 kept {len(P['kept'])} mask(s) in {seconds:.1f} s; the object's box {P['bbox']}, "
            f"the writer's boxes {P['chosen']['boxes']}, before 1.11.14 {P['parts']}")
    live = [o for o in objs if "page" in o["paths"]]

    # 2. The prompt writer names each object, on the frame with all but the object dimmed (named, as_words)
    for o in live:
        dimmed = (frame_prev * np.where(o["paths"]["page"]["mask_prev"], 1.0, DIM)[..., None]).astype(np.uint8)
        o["dimmed"] = upload(a.url, dimmed, f"{tag}_{o['name']}_dimmed.png", sent) if naming or "dimmed" in asked else None
        if not naming:
            continue
        n = o["naming"] = {"image": "dimmed", "request": NAME_REQUEST}
        try:
            got, n["seconds"] = run(a.url, "prompt", {"image": o["dimmed"], "request": NAME_REQUEST, "system": NAME_SYSTEM,
                                                      "max_length": 24}, a.limit)
            n["answer"] = text_of(got)
        except Exception as err:  # noqa: BLE001
            n["answer"], n["error"] = "", str(err)
        o["object"] = name_of(n["answer"])
        say(f"{o['name']}: the writer names it « {o['object'] or 'nothing'} »")

    # 3. SAM 3.1 by that name (as_words): what the page finds once the name is in the prompt bar
    for o in (live if "as_words" in asked else []):
        if not o.get("object"):
            continue
        try:
            got, seconds = run(a.url, "snap", {"image": frame_name, "words": o["object"], **o["points"]}, a.limit)
            Q = o["paths"]["name"] = path_of(a.url, o, o["object"], got, prev, work)
            Q["seconds"] = seconds
            say(f"{o['name']}: SAM 3.1 by the name « {o['object']} » kept {len(Q['kept'])} mask(s); the object's box {Q['bbox']}")
        except Exception as err:  # noqa: BLE001
            o["name_error"] = f"SAM 3.1 by name failed: {err}"
            say(f"{o['name']}: {o['name_error']}")

    # 4. The prompt writer: each request (app.writeCaption), then what the page makes of its answer
    for o in live:
        s, P, Q = o["stroke"], o["paths"]["page"], o["paths"].get("name")
        base = {"tool": "erase", "words": s["words"], **P["chosen"]}
        P["ask"], crop_ask, wide_ask = page(
            ("upsampleRequest", base),
            ("upsampleRequest", dict(base, bbox=to_crop(base["bbox"], P["crop"]), boxes=[to_crop(b, P["crop"]) for b in base["boxes"]])),
            ("upsampleRequest", dict(base, bbox=P["bbox"], boxes=P["parts"])))
        plan = {"page": ("frame", frame_name, P["ask"]), "dimmed": ("dimmed", o["dimmed"], P["ask"]),
                "wide": ("frame", frame_name, wide_ask)}
        if "crop" in asked:
            plan["crop"] = ("crop", upload(a.url, crop_image(frame, P["crop"]), f"{tag}_{o['name']}_crop.png", sent), crop_ask)
        if Q:
            Q["ask"] = page(("upsampleRequest", {"tool": "erase", "words": o["object"], **Q["chosen"]}))[0]
            plan["as_words"] = ("frame", frame_name, Q["ask"])
        for req in asked:
            r = o["requests"][req] = {"path": "name" if req == "as_words" and Q else "page"}
            R = Q if r["path"] == "name" else P
            if req == "own":
                r["caption"] = P["own"]
            elif req == "named":
                r.update(o["naming"], name=o["object"])
                r["caption"] = page(("caption", {"tool": "erase", "words": o["object"] or s["words"], "colors": [],
                                                 "color": "#ffffff", "bbox": P["bbox"]}))[0]
            elif req == "as_words" and not Q:
                r.update(name=o.get("object", ""), answer="", caption=P["own"],
                         error="no name" if not o.get("object") else "SAM 3.1 by name failed")
            else:
                seen, image_name, ask = plan[req]
                r.update(image=seen, request=ask["request"], system=ask["mode"])
                if req == "as_words":
                    r["name"] = o["object"]
                try:
                    got, r["seconds"] = run(a.url, "prompt", {"image": image_name, "request": ask["request"],
                                                              "system": system[ask["mode"]]}, a.limit)
                    r["answer"] = text_of(got)
                except Exception as err:  # noqa: BLE001
                    r["answer"], r["error"] = "", str(err)
                locked, text = ask["locked"], r["answer"]
                if text and req == "crop":  # the answer's boxes are on the crop: back on the frame, with the page's own rows
                    cap, rows = page(("splitTable", text))[0]
                    text, locked = (f"{cap} {json.dumps(rows_to_frame(rows, P['crop']))}" if rows else cap), P["ask"]["locked"]
                r["made"] = page(("reconcile", text, locked))[0] if text else ""
                r["refused"] = bool(r["made"]) and not page(("erasesPaint", r["made"], locked, R["paint"]))[0]
                r["caption"] = r["made"] if r["made"] and not r["refused"] else R["own"]
                if req == "page" and r["refused"] and not s["words"].strip() and P["core"]:
                    leave_out(a.url, frame_name, r, P, locked, prev, system, a.limit)
                    if r.get("cut"):
                        say(f"{o['name']}, page: the box without « {', '.join(r['others'])} » {r['cut']}; the writer again: "
                            f"« {short(r.get('again'), 140)} »")
            say(f"{o['name']}, {req}: {verdict(req, r)}. The writer: « {short(r.get('answer'), 140)} »")

    # 5. Klein: once per mask and caption that differ (app.generate)
    frame_work_name = upload(a.url, frame_work, f"{tag}_frame_full.png", sent) if a.full and live else None
    for o in live:
        masks = {}
        for r in o["requests"].values():
            key, R = edit_key(r), o["paths"][r["path"]]
            if key in o["edits"]:
                continue
            if r["path"] not in masks:
                masks[r["path"]] = (upload(a.url, white(R["mask_prev"]), f"{tag}_{o['name']}_{r['path']}_mask.png", sent),
                                    upload(a.url, white(R["mask_work"]), f"{tag}_{o['name']}_{r['path']}_mask_full.png", sent)
                                    if a.full else None)
            k = len(o["edits"])
            e = o["edits"][key] = {"index": k, "path": r["path"]}
            values = {"base": frame_name, "reference": frame_name, "start": frame_name, "caption": r["caption"], "seed": a.seed,
                      "plan": "", "mask": masks[r["path"]][0], "steps": QUICK["steps"], "denoise": QUICK["denoise"],
                      "grow": jround(prev[0] / EDIT_GROW), "feather": QUICK["feather"], "sigma": QUICK["sigma"],
                      "prefix": f"paintaplate/{tag}/{o['name']}_{k}"}
            try:
                got, e["quick_seconds"] = run(a.url, "edit", values, a.limit)
                patch = image(a.url, got["patch"]["images"][0], "RGBA")
                after = over(frame_prev, patch)
                if a.full:  # the page's full-size pass, from the quick result; the page measures this one
                    e["quick_share"] = shares(after, frame_prev, R["mask_prev"])
                    start = upload(a.url, over(frame_work, patch), f"{tag}_{o['name']}_{k}_start.png", sent)
                    got, e["full_seconds"] = run(a.url, "edit", dict(
                        values, base=frame_work_name, start=start, reference=start, mask=masks[r["path"]][1],
                        steps=FULL["steps"], denoise=FULL["denoise"], grow=jround(work[0] / EDIT_GROW), feather=FULL["feather"],
                        sigma=FULL["sigma"], relight=0, shade="", level=True), a.limit)
                    after = over(frame_prev, image(a.url, got["patch"]["images"][0], "RGBA"))
            except Exception as err:  # noqa: BLE001
                e["error"] = f"Klein failed: {err}"
                say(f"{o['name']}, caption {k}: {e['error']}")
                continue
            e["after"] = f"results/{o['name']}_{k}.png"
            Image.fromarray(after).save(os.path.join(out, e["after"]))
            o["afters"][key] = after
            e["share"], e["check"] = shares(after, frame_prev, R["mask_prev"]), check(after, frame_prev, R["mask_prev"])
            e["edges"] = e["check"]["edges"]
            used = [q for q, x in o["requests"].items() if edit_key(x) == key]
            say(f"{o['name']}, caption {k} ({', '.join(used)}): changed {' / '.join(pct(v) for v in e['share'])}, "
                f"edges {num(e['edges'])}")

    # 6. SAM 3.1 again, on every result: does it still find the object at the stroke's points?
    for o in live:
        for key, after in o["afters"].items():
            e = o["edits"][key]
            R = o["paths"][e["path"]]
            try:
                name = upload(a.url, after, f"{tag}_{o['name']}_{e['index']}_after.png", sent)
                got, _ = run(a.url, "snap", {"image": name, "words": R["words"], **o["points"]}, a.limit)
                again = np.zeros_like(R["sam"])
                for _, m in objects_of(a.url, got, o["painted"], o["points"], prev):
                    again |= m
                e["sam"] = overlap(again, R["sam"]) if R["sam"].any() else None
            except Exception as err:  # noqa: BLE001
                e["sam_error"] = str(err)

    seconds = time.time() - t0
    passes = (f"Klein's quick pass at {prev[0]} x {prev[1]}, {QUICK['steps']} steps" +
              (f", then the full-size pass at {work[0]} x {work[1]}, {FULL['steps']} steps at denoise {FULL['denoise']} "
               "(measured)" if a.full else " (measured)"))
    head = [f"# Erase probe · {os.path.basename(a.plate)} · {time.strftime('%d %B %Y, %H:%M')}", "",
            f"{facts}. Seed {a.seed}. {passes}. {len(strokes)} stroke(s), {seconds:.0f} s in all.", "",
            "The requests:", ""] + [f"- **{r}**: {REQUESTS[r]}." for r in asked] + [
            "", "« Changed »: the share of the object whose 4-pixel cells moved by more than 12, 24 and 48 levels of 255. "
            "The first is the page's rule (logic.erasedShare): under 2%, the page says that the object stayed. « Edges »: the "
            "correlation of the gradient inside the object, before and after (1: the same edges). « SAM again »: what SAM 3.1 "
            "keeps at the stroke's points on the result, over what it kept on the frame (1: the same object). « Seconds »: the "
            "writer, then Klein. Each is measured inside the mask Klein got: as_words has its own. « The page's check »: logic.eraseCheck, "
            "left when under 30% of the object moved by more than 24 levels, or when its edges held above 0.85."]
    report(os.path.join(out, "report.md"), objs, asked, head)
    sheet(os.path.join(out, "sheet.png"), objs, asked, frame_prev,
          f"{a.plate} · seed {a.seed} · {'quick and full-size passes' if a.full else 'quick pass'} · "
          f"the frame, then: {', '.join(asked)}")
    with open(os.path.join(out, "answers.json"), "w") as f:
        json.dump({"plate": a.plate, "seed": a.seed, "facts": facts, "work": work, "prev": prev, "full": a.full,
                   "seconds": round(seconds, 1), "requests": {r: REQUESTS[r] for r in asked},
                   "strokes": [plain(o) for o in objs]}, f, indent=1, ensure_ascii=False)
    for o in live:
        for req in asked:
            r = o["requests"][req]
            print(f"  {o['name']:<6} {req:<8} {short(verdict(req, r), 52):<52} {measured(o['edits'].get(edit_key(r), {}))}")
    say(f"Written to {out}: report.md, sheet.png and answers.json, with the images it sent and got back")


if __name__ == "__main__":
    main()
