"""Asks Klein for a relight of a plate's first frame in several ways on a running ComfyUI, and writes one sheet per set of
strokes: a study of the Light tool that changes nothing in the page.

    python tests/light_probe.py [PLATE ...] --out ~/paintaplate_gpu/light_probe [--url http://127.0.0.1:8188] [--seed 103]
        [--ways today,words,intent,intent_writer,intent_plan] [--sets sun,night] [--set "NAME|WORDS|#RRGGBB:x,y;x,y:SIZE|..."]

PLATE: a path under ComfyUI's input folder; with none, plates/horse.mp4 and plates/tea.mp4, two plates of the test data
(the dataset AInVFX/ainvfx-paintaplate on Hugging Face). The probe opens each plate with the page's own `ingest`, draws each set's strokes as the page's
canvas draws them, and runs the page's own workflows (prompt and edit in tools/build_workflows.py) at the edit preview's
size, 768 px on the long side: the first frame only, no shot. Run it in the tests' environment: the page's rules come from
web/logic.mjs, run by Node, as in tests/erase_probe.py.

The ways, for each set:
- today: what the page does (writeCaption and generate in web/app.mjs): the frame and the light plan (the strokes on grey,
  the shade in black) as Klein's two references, with the page's own request (logic.lightPlanCaption);
- words: the person's words alone, which Klein's prompt writer expands with the frame (its plain mode); Klein then gets the
  frame and the writer's prompt. A set with no words has no such way;
- intent: the strokes read as intentions (logic.lightIntent: each light's colour, strength, spread and place, the shade),
  with the words; Klein gets the frame and that prompt only;
- intent_writer: that prompt given to the prompt writer with the frame (plain mode), which reads the plate and writes the
  prompt that Klein gets with the frame;
- intent_plan: logic.lightIntent's prompt with the light plan as Klein's second reference, as today: what the plan adds.

Each result is measured against the frame, at the edit preview's size: edges, the correlation of the gradient's size before
and after over the whole frame (logic.eraseCheck: 1, the same edges); and the change of luminance in levels of 255, inside
the painted lights' boxes and elsewhere (a light that lands where it is painted lifts more inside).

The jobs are grouped by model, so that each model loads once on a 16 GB card: the prompt writer for every set, then Klein for
every way. It writes to --out: sheet_<plate>_<set>.png (the frame, the light plan, then each way), report.md (one row per
way, then every prompt in full), answers.json (all of it, for a script), and the images it sent and got back. ComfyUI keeps
its own copies under output/paintaplate/light_probe_<time>: delete them freely.
"""
import argparse
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from erase_probe import (EDIT_GROW, EDIT_SIDE, QUICK, REPO, about, check, first_frame, font_of, image, jround, page,  # noqa: E402
                         resized, run, short, stroke_mask, text_of, upload)

WAYS = {
    "today": "the page today: the frame and the light plan, with logic.lightPlanCaption",
    "words": "the person's words alone, through the prompt writer",
    "intent": "logic.lightIntent, the strokes read as intentions, with the words",
    "intent_writer": "logic.lightIntent through the prompt writer, which reads the plate",
    "intent_plan": "logic.lightIntent with the light plan, as today",
}
COLOR = "#ffd890"  # the Light tool's colour
with open(os.path.join(REPO, "web", "logic.mjs")) as _f:
    PLAN_GREY = re.search(r'export const PLAN_GREY = "(#[0-9a-fA-F]{6})"', _f.read()).group(1)
TILE = 384  # a sheet's tile, in pixels across
# The sets of strokes per plate, by its file name without the extension; any other plate gets those of "*". A stroke:
# (colour, points as (x, y) fractions of the frame, size in pixels on a frame 1920 pixels wide). Black strokes are shade.
SETS = {
    "horse": {
        "sun": ("warm low sun from the right", [(COLOR, [(0.92, 0.18), (0.95, 0.28), (0.92, 0.38)], 64)]),  # the GPU case horse_light
        "night": ("night, moonlight, and a lantern on the fence post", [("#8fb3ff", [(0.05, 0.05), (0.35, 0.08)], 160),
                                                                         ("#ffa040", [(0.94, 0.44), (0.95, 0.45)], 40)]),
        "shade": ("", [("#ffc070", [(0.03, 0.3), (0.03, 0.7)], 120), ("#000000", [(0.75, 0.6), (0.95, 0.9)], 200)]),
    },
    "*": {
        "lamp": ("a warm table lamp", [("#ffb060", [(0.2, 0.25), (0.22, 0.27)], 60)]),
        "window": ("cool daylight through a window on the right", [("#cfe2ff", [(0.97, 0.1), (0.97, 0.9)], 200)]),
        "candle": ("", [("#ff9a3c", [(0.5, 0.6), (0.51, 0.61)], 30), ("#000000", [(0.05, 0.05), (0.3, 0.4)], 220)]),
    },
}


def parse_set(text):
    """--set "NAME|WORDS|#RRGGBB:x,y;x,y:SIZE|...": (name, (words, strokes)), as in SETS."""
    name, words, *strokes = text.split("|")
    out = []
    for s in strokes:
        color, pts, size = s.split(":")
        out.append((color, [tuple(float(v) for v in p.split(",")) for p in pts.split(";")], float(size)))
    if not name or not out:
        sys.exit(f"--set takes NAME|WORDS|#RRGGBB:x,y;x,y:SIZE, one or more strokes: {text}")
    return name, (words, out)


def rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def plan_of(strokes, prev, darks):
    """app.lightPlan at `prev`: the strokes alone on grey, the shade in black under the light, drawn solid; and the boxes of
    the painted lights, as a mask."""
    w, h = prev
    plan = np.empty((h, w, 3), np.uint8)
    plan[:] = rgb(PLAN_GREY)
    lights = np.zeros((h, w), bool)
    for (color, pts, size), shade in sorted(zip(strokes, darks), key=lambda s: not s[1]):
        m = stroke_mask({"points": pts, "size": size / 1920 * w}, prev)
        plan[m] = (0, 0, 0) if shade else rgb(color)
        ys, xs = np.nonzero(m)
        if not shade and len(xs):
            lights[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = True
    return plan, lights


def lift(after, before, lights):
    """The change of luminance, in levels of 255: inside the painted lights' boxes, and elsewhere (None: no such pixel)."""
    weights = np.array([0.2126, 0.7152, 0.0722], np.float32)
    d = after[..., :3].astype(np.float32) @ weights - before[..., :3].astype(np.float32) @ weights
    return [float(d[m].mean()) if m.any() else None for m in (lights, ~lights)]


def sheet(path, r, ways):
    """The frame, the light plan, then each way's first frame, under a line that names the plate, the set and its words."""
    fh, fw = r["frame"].shape[:2]
    th = round(TILE * fh / fw)
    tiles = [("the frame", r["frame"]), ("the light plan", r["plan_img"])] + [(w, r["ways"].get(w, {}).get("image")) for w in ways]
    img = Image.new("RGB", (8 + len(tiles) * (TILE + 8), 66 + th), (24, 24, 24))
    d, big, small = ImageDraw.Draw(img), font_of(16), font_of(13)
    d.text((8, 8), f"{r['stem']} · {r['set']}: " + (f"« {r['words']} »" if r["words"] else "no words"), fill=(235, 235, 235), font=big)
    for i, (label, tile) in enumerate(tiles):
        x, w = 8 + i * (TILE + 8), r["ways"].get(label, {})
        said = label if tile is not None or label in ("the frame", "the light plan") else \
            f"{label}: {w.get('skipped') or short(w.get('error'), 40) or 'not run'}"
        d.text((x, 36), said, fill=(200, 200, 200), font=small)
        if tile is not None:
            img.paste(Image.fromarray(tile).resize((TILE, th), Image.BILINEAR), (x, 58))
    img.save(path)


def level(v):
    return "none" if v is None else f"{v:+.1f}"


def report(path, runs, ways, head):
    lines = list(head)
    for r in runs:
        lines += ["", f"## {r['stem']} · {r['set']}", "", (f"Words: « {r['words']} »." if r["words"] else "No words.") + " Strokes: " +
                  "; ".join(f"{c} from {list(pts[0])} to {list(pts[-1])}, {s:g} px across at 1920" for c, pts, s in r["strokes"]) +
                  f". Sheet: `sheet_{r['stem']}_{r['set']}.png`.", "",
                  "| Way | Seconds | Edges | Lift at the lights | Lift elsewhere | Prompt |", "| --- | --- | --- | --- | --- | --- |"]
        for way in ways:
            w = r["ways"].get(way, {})
            if "image" not in w:
                lines.append(f"| {way} | | | | | {w.get('skipped') or w.get('error') or 'not run'} |")
                continue
            secs = f"{w.get('writer_seconds', 0):.0f} + {w['seconds']:.0f}" if "writer_seconds" in w else f"{w['seconds']:.0f}"
            lines.append(f"| {way} | {secs} | {w['edges']:.2f} | {level(w['lift'][0])} | {level(w['lift'][1])} | "
                         f"{short(w['caption'], 120).replace('|', '/')} |")
        lines += ["", "In full:", ""]
        for way in ways:
            w = r["ways"].get(way, {})
            lines += [f"- {way}" + (f", asked of the writer: « {w['request']} »" if w.get("request") else "") + ":", "",
                      f"  {w.get('caption') or w.get('skipped') or w.get('error') or 'not run'}", ""]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plates", nargs="*", help="paths under ComfyUI's input folder (default: plates/horse.mp4 plates/tea.mp4)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--seed", type=int, default=103, help="Klein's seed for every way (default: the GPU case horse_light's)")
    ap.add_argument("--ways", default=",".join(WAYS), help="which ways, of: " + ", ".join(WAYS))
    ap.add_argument("--sets", default="", help="only the sets with these names, comma-separated")
    ap.add_argument("--set", action="append", default=[], help='a set of your own, for every plate: "NAME|WORDS|#RRGGBB:x,y;x,y:SIZE|..."')
    ap.add_argument("--limit", type=float, default=900, help="seconds that one job may take")
    a = ap.parse_args(argv)
    ways = [w.strip() for w in a.ways.split(",") if w.strip()]
    if not ways or set(ways) - set(WAYS):
        sys.exit(f"--ways takes some of: {', '.join(WAYS)}")
    plates, own, only = a.plates or ["plates/horse.mp4", "plates/tea.mp4"], dict(parse_set(t) for t in a.set), set(filter(None, a.sets.split(",")))
    out = os.path.abspath(os.path.expanduser(a.out))
    sent = os.path.join(out, "sent")
    os.makedirs(sent, exist_ok=True)
    os.makedirs(os.path.join(out, "results"), exist_ok=True)
    tag, t0 = f"light_probe_{time.strftime('%Y%m%d_%H%M%S')}", time.time()

    def say(text):
        print(f"{time.time() - t0:6.1f} s  {text}", flush=True)

    with open(os.path.join(REPO, "web", "upsampler.json")) as f:
        system = json.load(f)
    facts = about(a.url)
    say(f"{facts}. Plates: {', '.join(plates)}; ways: {', '.join(ways)}; seed {a.seed}")
    runs = []
    for plate in plates:  # each plate's first frame, and each set's plan and the page's two prompts
        frame = first_frame(a.url, plate, tag, a.limit)
        H, W = frame.shape[:2]
        prev = page(("fitSize", W, H, EDIT_SIDE, 16))[0]
        frame_prev, stem = resized(frame, prev), os.path.splitext(os.path.basename(plate.rstrip("/")))[0]
        frame_name = upload(a.url, frame_prev, f"{tag}_{stem}_frame.png", sent)
        whole = upload(a.url, np.full((prev[1], prev[0]), 255, np.uint8), f"{tag}_{stem}_whole.png", sent)  # a light's mask (app.maskAt)
        for name, (words, strokes) in (own or SETS.get(stem, SETS["*"])).items():
            if only and name not in only:
                continue
            darks = page(*[("dark", c) for c, _, _ in strokes])
            plan, lights = plan_of(strokes, prev, darks)
            today, intent = page(("lightPlanCaption", {"colors": [c for c, _, _ in strokes], "color": COLOR, "words": words}),
                                 ("lightIntent", {"strokes": [{"color": c, "size": s / 1920, "points": [list(p) for p in pts]}
                                                              for c, pts, s in strokes], "words": words, "aspect": W / H}))
            runs.append({"plate": plate, "stem": stem, "set": name, "words": words, "strokes": strokes, "size": [W, H],
                         "edit_preview": prev, "today": today, "intent": intent, "frame": frame_prev, "frame_name": frame_name,
                         "whole": whole, "plan_img": plan, "lights": lights, "ways": {},
                         "plan": upload(a.url, plan, f"{tag}_{stem}_{name}_plan.png", sent)})
        say(f"{plate}, {W} x {H}: the edit preview at {prev[0]} x {prev[1]}")

    # 1. The prompt writer, with the frame: the words, and the intentions
    for r in runs:
        for way, request in (("words", r["words"]), ("intent_writer", r["intent"])):
            if way not in ways:
                continue
            w = r["ways"][way] = {}
            if not request.strip():
                w["skipped"] = "no words"
                continue
            w["request"] = request
            try:
                got, w["writer_seconds"] = run(a.url, "prompt", {"image": r["frame_name"], "request": request, "system": system["plain"]}, a.limit)
                w["caption"] = text_of(got)
            except Exception as err:  # noqa: BLE001
                w["error"] = f"the prompt writer failed: {err}"
            say(f"{r['stem']} · {r['set']}, {way}: « {short(w.get('caption') or w.get('error'), 140)} »")

    # 2. Klein, at the edit preview's size: one pass per way, the frame as its start, every pixel open to change
    for r in runs:
        for way in ways:
            w = r["ways"].setdefault(way, {})
            if "skipped" in w or "error" in w:
                continue
            if way in ("today", "intent", "intent_plan"):
                w["caption"] = r["today"] if way == "today" else r["intent"]
            if not w.get("caption"):
                w["error"] = "the prompt writer gave nothing"
                continue
            values = {"base": r["frame_name"], "reference": r["frame_name"], "start": r["frame_name"], "caption": w["caption"],
                      "seed": a.seed, "plan": r["plan"] if way in ("today", "intent_plan") else "", "mask": r["whole"],
                      "steps": QUICK["steps"], "denoise": QUICK["denoise"], "grow": jround(r["edit_preview"][0] / EDIT_GROW),
                      "feather": QUICK["feather"], "sigma": QUICK["sigma"], "prefix": f"paintaplate/{tag}/{r['stem']}_{r['set']}_{way}"}
            try:
                got, w["seconds"] = run(a.url, "edit", values, a.limit)
                after = image(a.url, got["result"]["images"][0])
            except Exception as err:  # noqa: BLE001
                w["error"] = f"Klein failed: {err}"
                say(f"{r['stem']} · {r['set']}, {way}: {w['error']}")
                continue
            after = after if after.shape[:2] == r["frame"].shape[:2] else resized(after, r["edit_preview"])
            w["after"] = f"results/{r['stem']}_{r['set']}_{way}.png"
            Image.fromarray(after).save(os.path.join(out, w["after"]))
            w["image"], w["lift"] = after, lift(after, r["frame"], r["lights"])
            w["edges"] = check(after, r["frame"], np.ones(r["frame"].shape[:2], bool))["edges"]
            say(f"{r['stem']} · {r['set']}, {way}: {w['seconds']:.0f} s, edges {w['edges']:.2f}, "
                f"lift {level(w['lift'][0])} at the lights and {level(w['lift'][1])} elsewhere")

    # 3. One sheet per set, the report, and every answer
    for r in runs:
        sheet(os.path.join(out, f"sheet_{r['stem']}_{r['set']}.png"), r, ways)
    head = [f"# Light probe · {time.strftime('%Y-%m-%d %H:%M')}", "", f"{facts}. Seed {a.seed}. Klein at the edit preview's size, "
            f"{QUICK['steps']} steps, the first frame only.", "", "The ways:", ""] + [f"- {k}: {WAYS[k]}" for k in ways]
    report(os.path.join(out, "report.md"), runs, ways, head)
    keep = {"frame", "plan_img", "lights"}
    with open(os.path.join(out, "answers.json"), "w") as f:
        json.dump({"facts": facts, "seed": a.seed, "ways": ways, "sets": [
            {**{k: v for k, v in r.items() if k not in keep}, "ways": {k: {x: y for x, y in w.items() if x != "image"} for k, w in r["ways"].items()}}
            for r in runs]}, f, indent=1, default=str)
    say(f"Written to {out}: {len(runs)} sheet(s), report.md, answers.json")


if __name__ == "__main__":
    main()
