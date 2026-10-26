"""GPU checks on a machine with the models, against its local ComfyUI (run it on that machine).

    python tests/gpu_bench.py ingest <plate path> <colour space>
    python tests/gpu_bench.py edit <plate path> <colour space> <tool> <x0,y0,x1,y1> [words]
    python tests/gpu_bench.py shot <plate path> <colour space> <hero png in output> <width> <height> [replace|prepend]

Each step fills the pack's own workflows like the app does, times them and writes images and a
JSON line per run to /workspace/bench, for review.
"""
import json, os, sys, time, urllib.request
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

URL = "http://127.0.0.1:8188"
HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, "..", "web", "workflows")
COMFY = os.environ.get("COMFY", "/workspace/ComfyUI")
BENCH = "/workspace/bench"
os.makedirs(BENCH, exist_ok=True)


def call(path, body=None):
    r = urllib.request.Request(URL + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=600).read() or b"{}")


def fill(name, values, edit=None):
    sys.path.insert(0, os.path.join(HERE, "..", "tools"))
    from build_workflows import fill as fill_slots
    prompt = fill_slots(name, values, WF)
    if edit:
        edit(prompt)
    return prompt


def run(prompt, label):
    t0 = time.time()
    res = call("/prompt", {"prompt": prompt, "client_id": "bench"})
    if "prompt_id" not in res:
        raise SystemExit(f"{label}: rejected {json.dumps(res)[:800]}")
    pid = res["prompt_id"]
    while True:
        h = call(f"/history/{pid}")
        if pid in h and (h[pid]["status"].get("completed") or h[pid]["status"].get("status_str") == "error"):
            break
        time.sleep(0.2)
    dt = time.time() - t0
    err = next((m[1] for m in h[pid]["status"].get("messages", []) if m[0] == "execution_error"), None)
    outs = [f for o in h[pid]["outputs"].values() for k in ("images", "gifs", "video") for f in o.get(k, [])]
    texts = [t for o in h[pid]["outputs"].values() for t in o.get("text", [])]
    line = {"label": label, "seconds": round(dt, 2), "error": err and f"{err.get('node_type')}: {err.get('exception_message', '')[:300]}",
            "files": [f"{f['type']}/{f['subfolder']}/{f['filename']}" for f in outs][:4]}
    print(json.dumps(line)); open(f"{BENCH}/report.jsonl", "a").write(json.dumps(line) + "\n")
    return outs, texts, dt


def path_of(f):
    return os.path.join(COMFY, f["type"], f["subfolder"], f["filename"])


def fit(w, h, cap, step):
    """The page's fitSize: multiples of `step` that keep the aspect within 1.5%, as large as allowed."""
    long, short = max(w, h), min(w, h)
    top = max(step, min(cap, long) // step * step)
    best, size = None, top
    while size >= max(step, top * 0.75):
        s = max(step, int(short * size / long / step + 0.5) * step)
        err = abs(size / s - long / short) / (long / short)
        if best is None or err < best[2]:
            best = (size, s, err)
        if err <= 0.015:
            best = (size, s, err)
            break
        size -= step
    return [best[0], best[1]] if w >= h else [best[1], best[0]]


def ingest(plate, cs):
    outs, texts, _ = run(fill("ingest", {"path": plate, "color_space": cs, "prefix": "bench/hero", "video_prefix": "bench/proxy"}), f"ingest {plate}")
    spec = json.loads(texts[0])
    hero = next(path_of(f) for f in outs if f["filename"].endswith(".png"))
    Image.open(hero).save(f"{BENCH}/hero_{os.path.basename(plate)}.png")
    print(json.dumps({k: spec.get(k) for k in ("kind", "width", "height", "frames", "fps", "color_space_guess")}))
    return hero, spec


def inputs(hero, tool, box, size, tag):
    """What the page uploads: base, reference and mask at one size."""
    w, h = size
    base = Image.open(hero).convert("RGB").resize((w, h), Image.LANCZOS)
    x0, y0, x1, y1 = [int(v * s) for v, s in zip(box, (w, h, w, h))]
    mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).ellipse((x0, y0, x1, y1), fill=255)
    ref = base.copy()
    if tool == "paint":
        ImageDraw.Draw(ref).ellipse((x0, y0, x1, y1), fill=(245, 120, 20))
    elif tool == "light":
        glow = Image.new("RGB", (w, h), (0, 0, 0)); ImageDraw.Draw(glow).ellipse((x0, y0, x1, y1), fill=(255, 170, 60))
        ref = Image.fromarray(np.clip(np.asarray(ref, np.float32) + np.asarray(glow.filter(ImageFilter.GaussianBlur(w / 20)), np.float32), 0, 255).astype(np.uint8))
        mask = Image.new("L", (w, h), 255)
    sub = os.path.join(COMFY, "input", "bench"); os.makedirs(sub, exist_ok=True)
    names = {}
    for key, img in (("base", base), ("reference", ref), ("mask", mask)):
        img.save(os.path.join(sub, f"{tag}_{key}.png")); names[key] = f"bench/{tag}_{key}.png"
    return names, (x0, y0, x1, y1)


def caption(tool, box, words):
    bbox = [round(v * 1000) for v in (box[1], box[0], box[3], box[2])]
    text = {"erase": "Remove the object inside <obj_1> completely, with its shadow and its reflection. Show the surface and the background that continue behind it, with matching detail, light, shadows and focus. Add no new object. Keep everything else unchanged.",
            "paint": f"Replace the rough coloured drawing inside <obj_1> with {words}, in exactly the same style, lighting, perspective and grain as the rest of the image. Keep everything else unchanged.",
            "light": f"Relight the whole scene with {words} coming from <obj_1>, with physically consistent shadows and reflections. Keep the content, framing and textures unchanged."}[tool]
    desc = {"erase": "object to remove", "paint": words, "light": "light source"}[tool]
    return f"{text} {json.dumps([{'id': 'obj_1', 'bbox': bbox, 'desc': desc}])}"


def edit(plate, cs, tool, box, words=""):
    hero, spec = ingest(plate, cs)
    work = fit(spec["width"], spec["height"], 1920, 32); prev = fit(spec["width"], spec["height"], 768, 16)
    for klein in os.environ.get("KLEINS", "flux3-image-klein-int8-convrot.safetensors,flux3-image-klein-nvfp4.safetensors").split(","):
        q = "int8" if "int8" in klein else "nvfp4"
        names, _ = inputs(hero, tool, box, prev, f"{tool}_prev")
        light = tool == "light"
        base = dict(klein=klein, base=names["base"], reference=names["reference"],
                    start=names["base"] if light else names["reference"], mask=names["mask"],
                    caption=caption(tool, box, words), steps=8, denoise=0.65 if light else 1.0,
                    grow=prev[0] // (24 if tool == "erase" else 48), feather=6, sigma=3)
        for seed in (1, 2, 1):  # the third run is warm and cached text: the interactive case
            outs, _, dt = run(fill("edit", {**base, "seed": seed}), f"preview {tool} {q} seed {seed}")
            if outs:
                Image.open(path_of(outs[0])).save(f"{BENCH}/{tool}_{q}_preview_s{seed}.png")
        pick = f"{BENCH}/{tool}_{q}_preview_s1.png"
        names_w, _ = inputs(hero, tool, box, work, f"{tool}_work")
        start = os.path.join(COMFY, "input", "bench", f"{tool}_{q}_start.png")
        Image.open(pick).resize(tuple(work), Image.LANCZOS).save(start)
        steps = int(os.environ.get("REFINE_STEPS", "16"))
        outs, _, dt = run(fill("edit", {**base, "seed": 1, "steps": steps, "denoise": 0.35, "base": names_w["base"],
                                        "reference": names_w["reference"],
                                        "start": f"bench/{tool}_{q}_start.png", "mask": names_w["mask"],
                                        "grow": work[0] // (24 if tool == "erase" else 48), "feather": 12, "sigma": 6}),
                          f"refine {tool} {q} {steps} steps")
        if outs:
            Image.open(path_of(outs[0])).save(f"{BENCH}/{tool}_{q}_refined_{steps}.png")


def shot(plate, cs, hero, width, height, mode="replace"):
    def prepend(p):
        for node in p.values():
            if node["class_type"] == "ImageFromBatch" and node["inputs"].get("batch_index") == 1:
                node["inputs"]["batch_index"] = 0  # [hero, f0, f1, ...]; the latent length trims the extra frame
    outs, _, dt = run(fill("shot", {"path": plate, "color_space": cs, "max_frames": 121, "hero": hero, "width": int(width),
                                    "height": int(height), "seed": 7, "prefix": f"bench/shot_{mode}_{width}/f",
                                    "video_prefix": f"bench/shot_{mode}_{width}"}, prepend if mode == "prepend" else None),
                      f"shot {mode} {width}x{height}")
    return outs


def anime(w=1280, h=704, frames=121):
    """A test plate made with our own models: a FLUX 3 Image Klein frame, animated by LTX 2.5."""
    sys.path.insert(0, os.path.join(HERE, "..", "tools"))
    from build_workflows import GEMMA, KLEIN, LTX, NEGATIVE, Graph
    w, h, frames = int(w), int(h), int(frames)
    g = Graph()
    clip = g("CLIPLoader", clip_name="qwen3vl_4b_int8_convrot.safetensors", type="flux3", device="default")
    vae = g("VAELoader", vae_name="flux2-vae.safetensors")
    pos = g("CLIPTextEncode", clip=clip, text=(
        "2D anime film still, hand-painted background art in the style of a feature animation: a quiet Japanese shopping "
        "street at dusk, wooden shopfronts with cloth banners, a red vending machine on the left, a bicycle leaning on a "
        "lamp post, overhead power cables, warm orange sky, soft long shadows, clean cel shading, no people, no text"))
    first = g("VAEDecode", vae=vae, samples=g("KSampler", model=g("UNETLoader", unet_name=KLEIN, weight_dtype="default"),
              seed=11, steps=16, cfg=1.0, sampler_name="euler", scheduler="simple", positive=pos,
              negative=g("ConditioningZeroOut", conditioning=pos), denoise=1.0,
              latent_image=g("EmptyFlux2LatentImage", width=w, height=h, batch_size=1)))
    g("SaveImage", images=first, filename_prefix="bench/anime_first")
    model = g("UNETLoader", unet_name=LTX, weight_dtype="default")
    lclip = g("CLIPLoader", clip_name=GEMMA, type="ltxv", device="default")
    lvae = g("VAELoader", vae_name="ltx-2.5-video-vae-conv-bf16.safetensors")
    cond = g("LTXVConditioning", frame_rate=24.0, negative=g("CLIPTextEncode", text=NEGATIVE, clip=lclip),
             positive=g("CLIPTextEncode", clip=lclip, text=(
                 "2D anime style. The camera slowly pans right along a quiet shopping street at dusk. Cloth banners sway "
                 "gently in the wind and the power cables move slightly. Clean cel shading, steady camera, no people.")))
    latent = g("LTXVImgToVideoInplace", vae=lvae, image=first, strength=1.0, bypass=False,
               latent=g("EmptyLTXVLatentVideo", width=w, height=h, length=frames, batch_size=1))
    audio = g("LTXVEmptyLatentAudio", audio_vae=g("VAELoader", vae_name="ltx-2.5-audio-vae-bf16.safetensors"),
              frames_number=frames, frame_rate=24.0, batch_size=1)
    sampled = g("SamplerCustomAdvanced", noise=g("RandomNoise", noise_seed=11),
                guider=g("CFGGuider", model=model, positive=cond[0], negative=cond[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler_ancestral"),
                sigmas=g("ManualSigmas", sigmas="1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"),
                latent_image=g("LTXVConcatAVLatent", video_latent=latent, audio_latent=audio))
    video = g("LTXVSeparateAVLatent", av_latent=sampled[0])
    g("SaveImage", images=g("VAEDecode", samples=video[0], vae=lvae), filename_prefix="bench/anime/f")
    run(g.prompt, "anime plate")


def mp4(plate, out_name):
    """An H.264 copy of an EXR plate (display sRGB), to test the video path."""
    sys.path.insert(0, os.path.join(HERE, ".."))
    import plateio
    import OpenEXR
    files = plateio.find_sequence(os.path.join(COMFY, "input", plate))
    first = OpenEXR.File(files[0]).channels()
    h, w = next(iter(first.values())).pixels.shape[:2]
    spec = {"codec": "h264", "pix_fmt": "yuv420p", "width": w, "height": h, "fps": 24.0, "fps_num": 24, "fps_den": 1,
            "colorspace": 1, "color_primaries": 1, "color_trc": 1, "color_range": 1}
    out = os.path.join(COMFY, "input", "plates", out_name)
    writer = plateio.VideoWriter(spec, out)
    for f in files:
        ch = OpenEXR.File(f).channels(); rgb = ch.get("RGB", ch.get("RGBA")).pixels[..., :3].astype(np.float32)
        writer.write(np.clip(rgb / (1 + rgb), 0, 1) ** (1 / 2.2))
    writer.close()
    print("wrote", out, len(files), "frames", writer.notes)


def export(plate, cs, shot, matte_a, matte_b, relight="1"):
    on = relight == "1"
    run(fill("export", {"path": plate, "color_space": cs, "max_frames": 121, "shot": shot, "matte_a": matte_a, "matte_b": matte_b,
                        "relight": on, "keep_untouched": not on, "prefix": f"bench/export_{int(time.time())}"}), f"export relight={on}")


if __name__ == "__main__":
    step, args = sys.argv[1], sys.argv[2:]
    if step == "ingest":
        ingest(*args)
    elif step == "edit":
        edit(args[0], args[1], args[2], [float(v) for v in args[3].split(",")], " ".join(args[4:]))
    elif step == "shot":
        shot(*args)
    elif step == "export":
        export(*args)
    elif step == "anime":
        anime(*args)
    elif step == "mp4":
        mp4(*args)
