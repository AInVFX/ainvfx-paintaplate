"""Asks Klein for a paint on a plate's first frame in two ways on a running ComfyUI, and writes one sheet per set of
strokes: a study of how much the strokes' colours count, that changes nothing in the page.

    python tests/paint_probe.py [PLATE ...] --out ~/paintaplate_gpu/paint_probe [--url http://127.0.0.1:8188] [--seed 105]
        [--sets saddle,agree] [--set "NAME|WORDS|#RRGGBB:x,y;x,y:SIZE|..."]

PLATE: a path under ComfyUI's input folder; with none, plates/horse.mp4, a plate of the test data (the dataset
AInVFX/ainvfx-paintaplate on Hugging Face). The probe opens each plate with the page's own `ingest`, draws each set's
strokes over its first frame as the page's canvas draws them (each over the ones before), and runs the page's own
workflows (prompt and edit in tools/build_workflows.py) at the edit preview's size, 768 px on the long side: the first
frame only, no shot. The page's rules come from web/logic.mjs, run by Node, as in tests/erase_probe.py.

The ways, for each set:
- plain: the request to Klein's prompt writer with no colour by name (logic.upsampleRequest with no hues);
- colours: the page's request (writeCaption in web/app.mjs): the colours that the strokes show, by name, largest share first
  (logic.paintColors), unless the words name a colour. When it equals the plain request, Klein runs once and both show it.
The writer gets the frame with its strokes (table mode); Klein then gets that frame and the writer's caption.

It writes to --out: sheet_<plate>_<set>.png (the frame, the strokes on it, then each way), report.md (each request's
instruction and each caption in full) and answers.json. ComfyUI keeps its own copies under
output/paintaplate/paint_probe_<time>: delete them freely.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from erase_probe import (EDIT_GROW, EDIT_SIDE, QUICK, REPO, about, first_frame, font_of, image, jround, page,  # noqa: E402
                         resized, run, short, stroke_mask, text_of, upload)
from light_probe import parse_set, rgb  # noqa: E402

WAYS = {"plain": "the request with no colour by name", "colours": "the page's request: the strokes' colours by name, unless the words name one"}
TILE = 384
BACK = [(0.42, 0.43), (0.51, 0.43), (0.51, 0.47), (0.42, 0.47), (0.42, 0.51), (0.51, 0.51)]  # the horse's back (the GPU case horse_saddle)
# The sets of strokes per plate, by its file name without the extension. A stroke: (colour, points as (x, y) fractions of the
# frame, size in pixels on a frame 1920 pixels wide), drawn in this order, each over the ones before.
SETS = {
    "horse": {
        "saddle": ("saddle", [("#d32f2f", BACK, 44), ("#000000", [(0.44, 0.40), (0.49, 0.40), (0.49, 0.43), (0.44, 0.43)], 36)]),
        "agree": ("a red saddle blanket", [("#d32f2f", BACK, 44)]),
        "disagree": ("a red saddle blanket", [("#1976d2", BACK, 44)]),
        "no_words": ("", [("#fbc02d", BACK, 44)]),
    },
}


def layers(strokes, prev):
    """Which stroke shows at each pixel of the edit preview `prev` (-1: none), each over the ones before."""
    w, h = prev
    top = np.full((h, w), -1, np.int16)
    for k, (_, pts, size) in enumerate(strokes):
        top[stroke_mask({"points": pts, "size": size / 1920 * w}, prev)] = k
    return top


def shares_of(strokes, top):
    """The pixels that each colour shows, as the page counts them for logic.paintColors."""
    out = {}
    for k, (color, _, _) in enumerate(strokes):
        out[color] = out.get(color, 0) + int((top == k).sum())
    return out


def bbox_of(top):
    """The strokes' box, [y_min, x_min, y_max, x_max] on 0..1000."""
    ys, xs = np.nonzero(top >= 0)
    h, w = top.shape
    return [round(1000 * ys.min() / h), round(1000 * xs.min() / w), round(1000 * (ys.max() + 1) / h), round(1000 * (xs.max() + 1) / w)]


def sheet(path, r, ways):
    fh, fw = r["frame"].shape[:2]
    th = round(TILE * fh / fw)
    tiles = [("the frame", r["frame"], ""), ("the strokes", r["reference_img"], "")] + \
        [(w, r["ways"][w].get("image"), r["ways"][w].get("caption") or r["ways"][w].get("error") or "") for w in ways]
    img = Image.new("RGB", (8 + len(tiles) * (TILE + 8), 96 + th), (24, 24, 24))
    d, big, small = ImageDraw.Draw(img), font_of(16), font_of(13)
    named = f" · colours named: {', '.join(r['hues'])}" if r["hues"] else " · no colour named"
    d.text((8, 8), f"{r['stem']} · {r['set']}: " + (f"« {r['words']} »" if r["words"] else "no words") + named, fill=(235, 235, 235), font=big)
    for i, (label, tile, said) in enumerate(tiles):
        x = 8 + i * (TILE + 8)
        d.text((x, 36), label, fill=(200, 200, 200), font=small)
        if tile is not None:
            img.paste(Image.fromarray(tile).resize((TILE, th), Image.BILINEAR), (x, 58))
        if said:
            d.text((x, 64 + th), short(said, 58), fill=(170, 170, 170), font=small)
    img.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plates", nargs="*", help="paths under ComfyUI's input folder (default: plates/horse.mp4)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--seed", type=int, default=105, help="Klein's seed for every way (default: the GPU case horse_saddle's)")
    ap.add_argument("--sets", default="", help="only the sets with these names, comma-separated")
    ap.add_argument("--set", action="append", default=[], help='a set of your own, for every plate: "NAME|WORDS|#RRGGBB:x,y;x,y:SIZE|..."')
    ap.add_argument("--limit", type=float, default=900, help="seconds that one job may take")
    a = ap.parse_args(argv)
    plates, own, only = a.plates or ["plates/horse.mp4"], dict(parse_set(t) for t in a.set), set(filter(None, a.sets.split(",")))
    out = os.path.abspath(os.path.expanduser(a.out))
    sent = os.path.join(out, "sent")
    os.makedirs(sent, exist_ok=True)
    os.makedirs(os.path.join(out, "results"), exist_ok=True)
    tag, t0, ways = f"paint_probe_{time.strftime('%Y%m%d_%H%M%S')}", time.time(), list(WAYS)

    def say(text):
        print(f"{time.time() - t0:6.1f} s  {text}", flush=True)

    with open(os.path.join(REPO, "web", "upsampler.json")) as f:
        system = json.load(f)
    facts = about(a.url)
    say(f"{facts}. Plates: {', '.join(plates)}; seed {a.seed}")
    runs = []
    for plate in plates:
        frame = first_frame(a.url, plate, tag, a.limit)
        H, W = frame.shape[:2]
        prev = page(("fitSize", W, H, EDIT_SIDE, 16))[0]
        frame_prev, stem = resized(frame, prev), os.path.splitext(os.path.basename(plate.rstrip("/")))[0]
        frame_name = upload(a.url, frame_prev, f"{tag}_{stem}_frame.png", sent)
        for name, (words, strokes) in (own or SETS.get(stem, {})).items():
            if only and name not in only:
                continue
            top = layers(strokes, prev)
            ref = frame_prev.copy()
            for k, (color, _, _) in enumerate(strokes):
                ref[top == k] = rgb(color)
            hues = page(("paintColors", {"words": words, "shares": shares_of(strokes, top)}))[0]
            r = {"plate": plate, "stem": stem, "set": name, "words": words, "strokes": strokes, "hues": hues, "bbox": bbox_of(top),
                 "frame": frame_prev, "frame_name": frame_name, "reference_img": ref, "edit_preview": prev, "ways": {w: {} for w in ways},
                 "reference": upload(a.url, ref, f"{tag}_{stem}_{name}_ref.png", sent),
                 "mask": upload(a.url, np.where(top >= 0, 255, 0).astype(np.uint8), f"{tag}_{stem}_{name}_mask.png", sent)}
            runs.append(r)
        say(f"{plate}, {W} x {H}: the edit preview at {prev[0]} x {prev[1]}")

    # 1. The prompt writer, with the frame and its strokes: each way's request
    for r in runs:
        for way in ways:
            w = r["ways"][way]
            ask = page(("upsampleRequest", {"tool": "paint", "words": r["words"], "bbox": r["bbox"], "hues": r["hues"] if way == "colours" else []}))[0]
            w["request"] = ask["request"]
            if way == "colours" and ask["request"] == r["ways"]["plain"].get("request"):
                w["same"] = "plain"
                continue
            try:
                got, w["writer_seconds"] = run(a.url, "prompt", {"image": r["reference"], "request": ask["request"], "system": system[ask["mode"]]}, a.limit)
                text = text_of(got).strip()
                w["caption"] = page(("reconcile", text, ask["locked"]))[0] if text else \
                    page(("caption", {"tool": "paint", "words": r["words"], "bbox": r["bbox"], "hues": r["hues"] if way == "colours" else []}))[0]
            except Exception as err:  # noqa: BLE001
                w["error"] = f"the prompt writer failed: {err}"
            say(f"{r['stem']} · {r['set']}, {way}: « {short(w.get('caption') or w.get('error'), 140)} »")

    # 2. Klein, at the edit preview's size, inside the strokes' mask
    for r in runs:
        for way in ways:
            w = r["ways"][way]
            if "same" in w or "error" in w:
                continue
            values = {"base": r["frame_name"], "reference": r["reference"], "start": r["frame_name"], "caption": w["caption"], "seed": a.seed,
                      "mask": r["mask"], "steps": QUICK["steps"], "denoise": QUICK["denoise"], "grow": jround(r["edit_preview"][0] / EDIT_GROW),
                      "feather": QUICK["feather"], "sigma": QUICK["sigma"], "prefix": f"paintaplate/{tag}/{r['stem']}_{r['set']}_{way}"}
            try:
                got, w["seconds"] = run(a.url, "edit", values, a.limit)
                after = image(a.url, got["result"]["images"][0])
            except Exception as err:  # noqa: BLE001
                w["error"] = f"Klein failed: {err}"
                continue
            w["image"] = after if after.shape[:2] == r["frame"].shape[:2] else resized(after, r["edit_preview"])
            Image.fromarray(w["image"]).save(os.path.join(out, "results", f"{r['stem']}_{r['set']}_{way}.png"))
            say(f"{r['stem']} · {r['set']}, {way}: {w['seconds']:.0f} s")
        if "same" in r["ways"]["colours"]:
            r["ways"]["colours"].update({k: r["ways"]["plain"].get(k) for k in ("image", "caption", "error") if r["ways"]["plain"].get(k) is not None})

    # 3. One sheet per set, the report, and every answer
    lines = [f"# Paint probe · {time.strftime('%Y-%m-%d %H:%M')}", "", f"{facts}. Seed {a.seed}. Klein at the edit preview's size, "
             f"{QUICK['steps']} steps, the first frame only.", ""]
    for r in runs:
        sheet(os.path.join(out, f"sheet_{r['stem']}_{r['set']}.png"), r, ways)
        lines += [f"## {r['stem']} · {r['set']}", "", (f"Words: « {r['words']} »." if r["words"] else "No words.") +
                  f" Colours named: {', '.join(r['hues']) or 'none'}. Sheet: `sheet_{r['stem']}_{r['set']}.png`.", ""]
        for way in ways:
            w = r["ways"][way]
            lines += [f"- {way}" + (" (the same request as plain)" if "same" in w else "") + ":", "",
                      f"  {w.get('caption') or w.get('error') or 'not run'}", ""]
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    keep = {"frame", "reference_img"}
    with open(os.path.join(out, "answers.json"), "w") as f:
        json.dump({"facts": facts, "seed": a.seed, "sets": [{**{k: v for k, v in r.items() if k not in keep},
                   "ways": {k: {x: y for x, y in w.items() if x != "image"} for k, w in r["ways"].items()}} for r in runs]}, f, indent=1, default=str)
    say(f"Written to {out}: {len(runs)} sheet(s), report.md, answers.json")


if __name__ == "__main__":
    main()
