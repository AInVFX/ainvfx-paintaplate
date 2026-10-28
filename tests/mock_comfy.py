"""A stand-in ComfyUI for working on the page without a GPU: the same HTTP and WebSocket API, fake models.

    python tests/mock_comfy.py --root /tmp/mock --port 8199 [--plate]

It serves web/ at /extensions/ainvfx-paintaplate/, answers /object_info, /upload/image, /prompt, /history,
/view, /queue, /interrupt and /ws, and runs each workflow with numpy instead of models: an edit tints and
blurs the reference inside the mask and streams step previews, the shot pastes the edited first frame over
every frame, the matte repeats the first mask, the composite and the export blend through the matte. The
download route and the plate browser are the pack's own routes.py. --plate writes a 1280 x 704 test plate to input/plates/desk.mp4.
Each job waits a little, so the page's progress, cancelling and ordering behave as they do on a GPU.
"""
import argparse, asyncio, importlib, io, json, os, struct, sys, time, types, uuid
from fractions import Fraction

import av
import numpy as np
from aiohttp import web
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [REPO, os.path.join(REPO, "tools")]
import plateio  # noqa: E402
from build_workflows import outputs_of  # noqa: E402

A = None  # parsed arguments
JOBS, HISTORY, SOCKETS = [], {}, {}
STATE = {"running": None, "interrupt": False}


def folder(kind):
    return os.path.join(A.root, kind)


def make_plate(path, w=1280, h=704, n=49):
    """A slow pan over a textured desk with a red bottle that should be erased."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = av.open(path, "w")
    vs = out.add_stream("libx264", rate=Fraction(24, 1))
    vs.width, vs.height, vs.pix_fmt = w, h, "yuv420p"
    vs.codec_context.options = {"crf": "16"}
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rng = np.random.default_rng(1)
    grain = rng.normal(0, 4, (h, w + 200, 3)).astype(np.float32)
    for i in range(n):
        x = xx + i * 3.0  # the camera pans right
        wood = 0.5 + 0.18 * np.sin(x / 23.0 + np.sin(yy / 41.0) * 2.5) + 0.06 * np.sin(x / 5.0)
        img = np.stack([wood * 205, wood * 150, wood * 95], -1)
        img[: h // 3] = np.array([200, 205, 215]) * (0.75 + 0.25 * yy[: h // 3, :, None] / (h / 3))  # a wall
        cx = 760 - i * 3.0
        bottle = ((xx - cx) / 46) ** 2 + ((yy - 360) / 120) ** 2 < 1
        img[bottle] = np.array([180, 30, 28]) * (0.8 + 0.2 * np.cos((xx[bottle] - cx) / 30))[:, None]
        img = np.clip(img + grain[:, i * 3 % 200: i * 3 % 200 + w], 0, 255).astype(np.uint8)
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        frame.pts = i
        for p in vs.encode(frame):
            out.mux(p)
    for p in vs.encode(None):
        out.mux(p)
    out.close()
    print("plate:", path)


# ---------- reading and writing frames ----------

def resolve(path):
    root = folder("output") if path.startswith("output:") else folder("input")
    return os.path.join(root, path.removeprefix("output:"))


def read_plate(path, max_frames=1024, pad=False):
    full = resolve(path)
    spec = plateio.probe_plate(full)
    if spec["kind"] == "video":
        with av.open(full) as c:
            frames = [f.to_ndarray(format="rgb24").astype(np.float32) / 255 for f in c.decode(video=0)][:max_frames]
    else:
        frames = [np.asarray(Image.open(f).convert("RGB"), np.float32) / 255 for f in spec["files"][:max_frames]]
    n = len(frames)
    spec.update(frames=n, color_space_guess="sRGB")
    if pad:
        frames += [frames[-1]] * (plateio.pad_count_8n1(n) - n)
    return frames, spec


def load_image(name, mode="RGB"):
    sub, _, file = name.rpartition("/")
    path = os.path.join(folder("input"), sub, file.split(" [")[0])
    return np.asarray(Image.open(path).convert(mode), np.float32) / 255


def resize(img, w, h):
    mode = "L" if img.ndim == 2 else ("RGBA" if img.shape[2] == 4 else "RGB")
    arr = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(arr, mode).resize((w, h), Image.BILINEAR), np.float32) / 255


def save_png(img, kind, prefix, i=None):
    sub, _, stem = prefix.rpartition("/")
    d = os.path.join(folder(kind), sub)
    os.makedirs(d, exist_ok=True)
    name = f"{stem}_{(i or 0) + 1:05d}_.png"
    mode = "L" if img.ndim == 2 else ("RGBA" if img.shape[2] == 4 else "RGB")
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), mode).save(os.path.join(d, name))
    return {"filename": name, "subfolder": sub, "type": kind}


def save_mp4(frames, prefix, fps=24.0):
    sub, _, stem = prefix.rpartition("/")
    d = os.path.join(folder("output"), sub)
    os.makedirs(d, exist_ok=True)
    name = f"{stem}_00001_.webm"  # VP9: Playwright's Chromium has no H.264 decoder; ComfyUI itself writes H.264 MP4
    h, w = frames[0].shape[:2]
    out = av.open(os.path.join(d, name), "w")
    vs = out.add_stream("libvpx-vp9", rate=Fraction(fps).limit_denominator(1001))
    vs.width, vs.height, vs.pix_fmt = w - w % 2, h - h % 2, "yuv420p"
    vs.codec_context.options = {"deadline": "realtime", "cpu-used": "8", "crf": "34", "b": "0"}
    for i, f in enumerate(frames):
        fr = av.VideoFrame.from_ndarray((np.clip(f[: h - h % 2, : w - w % 2, :3], 0, 1) * 255).astype(np.uint8), format="rgb24")
        fr.pts = i
        for p in vs.encode(fr):
            out.mux(p)
    for p in vs.encode(None):
        out.mux(p)
    out.close()
    return {"filename": name, "subfolder": sub, "type": "output"}


# ---------- the fake workflows ----------

def inputs_by_slot(prompt):
    vals = {}
    for node in prompt.values():
        for key, slot in node.get("_meta", {}).get("slots", {}).items():
            if key in node["inputs"]:  # an optional link the page dropped keeps its slot name in _meta
                vals[slot] = node["inputs"][key]
    return vals


async def steps(pid, total, seconds, preview=None):
    for k in range(total):
        if STATE["interrupt"]:
            raise asyncio.CancelledError()
        await asyncio.sleep(seconds / total)
        await send({"type": "progress", "data": {"prompt_id": pid, "value": k + 1, "max": total}})
        if preview is not None:
            await send_preview(pid, preview(k + 1, total))


async def send_preview(pid, img):
    buf = io.BytesIO()
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(buf, "JPEG", quality=80)
    meta = json.dumps({"prompt_id": pid, "image_type": "image/jpeg", "node_id": "16"}).encode()
    msg = struct.pack(">II", 4, len(meta)) + meta + buf.getvalue()
    for ws in list(SOCKETS.values()):
        await ws.send_bytes(msg)


async def execute(pid, prompt):
    outs = outputs_of(prompt)
    v = inputs_by_slot(prompt)
    o = {}
    if "spec" in outs:  # ingest
        frames, spec = read_plate(v["path"], v.get("max_frames", 121), pad=True)
        n = spec["frames"]
        h, w = frames[0].shape[:2]
        k = min(1.0, 1920 / max(w, h))
        o[outs["hero"]] = {"images": [save_png(resize(frames[0], round(w * k), round(h * k)), "output", v["prefix"])]}
        k = min(1.0, v.get("proxy_size", 960) / max(w, h))
        pw, ph = round(w * k), round(h * k)
        o[outs["proxy"]] = {"images": [save_mp4([resize(f, pw, ph) for f in frames[:n]], v["video_prefix"], spec["fps"])],
                            "animated": [True]}
        o[outs["spec"]] = {"text": [plateio.spec_json(spec)]}
        await steps(pid, 2, 0.4)
    elif "text" in outs:  # prompt: the request comes back as the caption
        o[outs["text"]] = {"text": [v.get("request", "")]}
        await steps(pid, 1, 0.2)
    elif "patch" in outs:  # edit: a tinted, softened copy of the reference inside the mask, with step previews
        base, ref = load_image(v["base"]), load_image(v["reference"])
        mask = load_image(v["mask"], "L")
        soft = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9)).filter(
            ImageFilter.GaussianBlur(max(2, base.shape[1] / 120))), np.float32) / 255
        if "Relight" in v["caption"]:
            new = base * np.array([1.18, 1.0, 0.8]) + 0.12 * ref
        elif v["caption"].startswith("Remove"):
            new = np.asarray(Image.fromarray((ref * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)), np.float32) / 255
        else:
            new = np.asarray(Image.fromarray((ref * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)), np.float32) / 255
            new = new * np.array([1.0, 0.95, 0.9])
        new = np.clip(new, 0, 1)
        rng = np.random.default_rng(v.get("seed", 0))
        ph, pw = max(8, base.shape[0] // 16), max(8, base.shape[1] // 16)

        def look(k, total):  # what a latent preview looks like: small, noisy, clearer at each step
            small = resize(new, pw, ph)
            noise = rng.random(small.shape).astype(np.float32)
            t = k / total
            return small * t + noise * (1 - t)
        await steps(pid, v.get("steps", 8), 0.25 * v.get("steps", 8) * (1 if base.shape[1] < 1000 else 3), look)
        result = new * soft[..., None] + base * (1 - soft[..., None])
        o[outs["result"]] = {"images": [save_png(result, "temp", f"paintaplate/{pid[:8]}_result")]}
        o[outs["patch"]] = {"images": [save_png(np.dstack([new, soft]), "temp", f"paintaplate/{pid[:8]}_patch")]}
        if "relit" in outs:
            o[outs["relit"]] = {"images": [save_png(result, "temp", f"paintaplate/{pid[:8]}_relit")]}
    elif "point_0" in outs:  # snap: an object around each point it was given, none found by name
        img = load_image(v["image"])
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        for k in range(5):
            disc = np.zeros((h, w), bool)
            for p in json.loads(v.get(f"point_{k}") or "[]"):
                disc |= ((xx - p["x"]) / (0.05 * w)) ** 2 + ((yy - p["y"]) / (0.14 * h)) ** 2 < 1
            o[outs[f"point_{k}"]] = {"images": [save_png(disc.astype(np.float32), "temp", f"paintaplate/{pid[:8]}_snap{k}")]}
        if "named" in outs:
            o[outs["named"]] = {"images": []}
        await steps(pid, 2, 0.5)
    elif "frames" in outs and "video" in outs:  # shot: the edited first frame pasted on every frame
        frames, spec = read_plate(v["path"], v["max_frames"], pad=True)
        w, h = v["width"], v["height"]
        frames = [resize(f, w, h) for f in frames]
        hero = resize(load_image(v["hero"]), w, h)
        changed = (np.abs(hero - frames[0]).max(-1) > 0.08).astype(np.float32)
        changed = np.asarray(Image.fromarray((changed * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5)), np.float32)[..., None] / 255
        await steps(pid, v.get("steps", 8), 3.0)
        shot = [hero * changed + f * (1 - changed) for f in frames]
        shot[0] = hero
        o[outs["frames"]] = {"images": [save_png(f, "output", v["prefix"], i) for i, f in enumerate(shot)][:1]}
        o[outs["video"]] = {"images": [save_mp4(shot, v["video_prefix"], spec["fps"])], "animated": [True]}
    elif "frames" in outs:  # matte: the first mask on every frame
        frames, _ = read_plate(v["path"], v["max_frames"], pad=True)
        m = resize(load_image(v["mask"], "L"), v["width"], v["height"])
        await steps(pid, 4, 1.0)
        o[outs["frames"]] = {"images": [save_png(m, "output", v["prefix"], i) for i in range(len(frames))][:1]}
    elif "video" in outs or "export" in outs:  # comp and export: blend the shot over the plate through the matte
        frames, spec = read_plate(v["path"], v["max_frames"], pad=True)
        n = spec["frames"]
        h, w = (v["height"], v["width"]) if "video" in outs else frames[0].shape[:2]
        shot, _ = read_plate(v["shot"], 1024)
        has_matte = bool(v.get("matte_a"))
        matte = read_plate(v["matte_a"], 1024)[0] if has_matte else None
        await steps(pid, 6, 1.5 if "video" in outs else 3.0)
        out = []
        for i in range(n):
            p, g = resize(frames[i], w, h), resize(shot[min(i, len(shot) - 1)], w, h)
            m = resize(matte[min(i, len(matte) - 1)][..., 0], w, h)[..., None] if has_matte else np.ones((h, w, 1), np.float32)
            out.append(g * m + p * (1 - m))
        if "video" in outs:
            o[outs["video"]] = {"images": [save_mp4(out, v["video_prefix"], spec["fps"])], "animated": [True]}
        else:
            d = os.path.join(folder("output"), v["prefix"])
            os.makedirs(d, exist_ok=True)
            save_mp4(out, f"{v['prefix']}/plate", spec["fps"])
            if "matte" in outs:
                for i in range(n):
                    save_png(resize(matte[min(i, len(matte) - 1)][..., 0], w, h) if has_matte else np.zeros((h, w)),
                             "output", v["matte_prefix"], i)
            o[outs["export"]] = {"text": [f"1 file(s) in {d}\nplate_00001_.mp4"]}
            if "review" in outs:
                o[outs["review"]] = {"images": [save_mp4(out, v.get("review_prefix", f"{v['prefix']}/review"), spec["fps"])], "animated": [True]}
    else:
        await steps(pid, 1, 0.2)
    return o


# ---------- the API ----------

async def send(msg):
    for ws in list(SOCKETS.values()):
        await ws.send_str(json.dumps(msg))


async def worker():
    while True:
        if not JOBS:
            await asyncio.sleep(0.05)
            continue
        pid, prompt = JOBS.pop(0)
        STATE.update(running=pid, interrupt=False)
        await send({"type": "execution_start", "data": {"prompt_id": pid}})
        try:
            outputs = await execute(pid, prompt)
            HISTORY[pid] = {"outputs": outputs, "status": {"completed": True, "status_str": "success", "messages": []}}
            await send({"type": "execution_success", "data": {"prompt_id": pid}})
        except asyncio.CancelledError:
            HISTORY[pid] = {"outputs": {}, "status": {"completed": False, "status_str": "error", "messages": []}}
            await send({"type": "execution_interrupted", "data": {"prompt_id": pid}})
        except Exception as exc:  # report like ComfyUI does
            import traceback
            traceback.print_exc()
            HISTORY[pid] = {"outputs": {}, "status": {"completed": False, "status_str": "error", "messages": []}}
            await send({"type": "execution_error", "data": {"prompt_id": pid, "node_type": "Mock", "exception_message": str(exc)}})
        STATE["running"] = None


async def prompt_route(request):
    body = await request.json()
    pid = str(uuid.uuid4())
    if body.get("front"):
        JOBS.insert(0, (pid, body["prompt"]))
    else:
        JOBS.append((pid, body["prompt"]))
    return web.json_response({"prompt_id": pid, "number": len(HISTORY), "node_errors": {}})


async def history_route(request):
    pid = request.match_info["pid"]
    return web.json_response({pid: HISTORY[pid]} if pid in HISTORY else {})


async def view_route(request):
    q = request.query
    path = os.path.join(folder(q.get("type", "output")), q.get("subfolder", ""), q["filename"])
    return web.FileResponse(path)


async def upload_route(request):
    data = await request.post()
    f, sub = data["image"], data.get("subfolder", "")
    d = os.path.join(folder("input"), sub)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f.filename), "wb") as out:
        out.write(f.file.read())
    return web.json_response({"name": f.filename, "subfolder": sub, "type": "input"})


async def queue_route(request):
    body = await request.json()
    gone = set(body.get("delete", []))
    JOBS[:] = [j for j in JOBS if j[0] not in gone]
    return web.json_response({})


async def interrupt_route(request):
    body = await request.json() if request.can_read_body else {}
    if not body.get("prompt_id") or body["prompt_id"] == STATE["running"]:
        STATE["interrupt"] = True
    return web.json_response({})


SPACES = ["sRGB", "HDR", "HDR ACEScct", "HDR LogC3", "HDR PQ", "linear", "linear ACEScg"]


async def object_info_route(request):
    cls = request.match_info["cls"]
    models = {}
    for name in os.listdir(os.path.join(REPO, "web", "workflows")):
        for node in json.load(open(os.path.join(REPO, "web", "workflows", name))).values():
            for k, val in node["inputs"].items():
                if isinstance(val, str) and val.endswith(".safetensors"):
                    models.setdefault(node["class_type"], {}).setdefault(k, []).append(val)
    required = {k: [opts] for k, opts in models.get(cls, {}).items()}
    if cls == "ImageColorSpace":
        required["source"] = ["COMBO", {"options": SPACES}]
    return web.json_response({cls: {"input": {"required": required}}})


async def ws_route(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    cid = request.query.get("clientId", str(uuid.uuid4()))
    SOCKETS[cid] = ws
    await ws.send_str(json.dumps({"type": "status", "data": {"sid": cid}}))
    async for _ in ws:
        pass
    SOCKETS.pop(cid, None)
    return ws


def download_routes():
    """The pack's own routes.py (the download, the plate browser), with ComfyUI's folder_paths stubbed."""
    fp = types.ModuleType("folder_paths")
    fp.get_output_directory = lambda: folder("output")
    fp.get_input_directory = lambda: folder("input")
    fp.get_temp_directory = lambda: folder("temp")
    sys.modules["folder_paths"] = fp
    server = types.SimpleNamespace(routes=web.RouteTableDef())
    importlib.import_module("routes").setup(server)
    return server.routes


async def start():
    app = web.Application(client_max_size=1024 ** 3)
    app.router.add_post("/prompt", prompt_route)
    app.router.add_get("/history", lambda r: web.json_response({}))  # the page reads it once at start, for the models already loaded
    app.router.add_get("/history/{pid}", history_route)
    app.router.add_get("/view", view_route)
    app.router.add_post("/upload/image", upload_route)
    app.router.add_post("/queue", queue_route)
    app.router.add_post("/interrupt", interrupt_route)
    app.router.add_get("/object_info/{cls}", object_info_route)
    app.router.add_get("/system_stats", lambda r: web.json_response({"system": {}}))
    app.router.add_get("/ws", ws_route)
    app.router.add_routes(download_routes())
    app.router.add_static("/extensions/ainvfx-paintaplate/", os.path.join(REPO, "web"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", A.port).start()
    print(f"mock ComfyUI on http://127.0.0.1:{A.port}/extensions/ainvfx-paintaplate/paintaplate.html", flush=True)
    await worker()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/tmp/mock_comfy")
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--plate", action="store_true")
    A = ap.parse_args()
    for k in ("input", "output", "temp"):
        os.makedirs(folder(k), exist_ok=True)
    if A.plate:
        make_plate(os.path.join(folder("input"), "plates", "desk.mp4"))
    t0 = time.time()
    asyncio.run(start())
