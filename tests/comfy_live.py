"""Live test against a real ComfyUI (CPU is enough): no models are run.

    python tests/comfy_live.py --comfy /path/to/ComfyUI --python /path/to/python [--url http://127.0.0.1:8188]

1. Starts ComfyUI (unless --url points at a running one) with this pack installed.
2. Checks the nodes, the app page and the frontend extension are served.
3. Posts all five workflows with realistic values: ComfyUI's own validator must accept each one.
   Model files may be empty placeholders: model workflows are cancelled right after validation.
4. Runs `ingest` and `export` end to end on an EXR sequence with extra layers, a ProRes MOV
   with audio and timecode, and a 16-bit PNG sequence, then checks the files on disk.
"""
import argparse, json, os, shutil, subprocess, sys, time, urllib.request, uuid
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import plateio  # noqa: E402
import test_plateio  # noqa: E402
import OpenEXR  # noqa: E402

N, W, H = 17, 192, 108
FAILS = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        FAILS.append(what)


def http(url, data=None, files=None, timeout=60):
    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in (data or {}).items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, (name, blob) in files.items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode() + blob + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    elif data is not None:
        req = urllib.request.Request(url, json.dumps(data).encode(), {"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, ctype = r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw, ctype = e.read(), e.headers.get("Content-Type", "")
    return (json.loads(raw) if "json" in ctype else raw), ctype


def fill(name, values):
    wf = json.load(open(os.path.join(HERE, "..", "web", "workflows", f"{name}.json")))
    for slot, value in values.items():
        for nid, inp in wf["slots"].get(slot, []):
            wf["prompt"][nid]["inputs"][inp] = value
    return wf


def submit(url, prompt):
    res, _ = http(f"{url}/prompt", {"prompt": prompt, "client_id": "paintaplate-test"})
    return res


def wait(url, pid, limit=240):
    t0 = time.time()
    while time.time() - t0 < limit:
        h, _ = http(f"{url}/history/{pid}")
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                return h[pid], time.time() - t0
        time.sleep(0.5)
    return None, limit


def error_of(entry):
    for kind, msg in entry.get("status", {}).get("messages", []):
        if kind == "execution_error":
            return f"{msg.get('node_type')}: {msg.get('exception_message', '').strip()[:300]}"
    return None


def make_plates(input_dir):
    root = os.path.join(input_dir, "paintaplate_test")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "exr"))
    test_plateio.make_exr_sequence(os.path.join(root, "exr"), n=N, h=H, w=W)
    test_plateio.make_prores(os.path.join(root, "plate.mov"), n=N, w=W, h=H)
    png = os.path.join(root, "png16"); os.makedirs(png)
    rng = np.random.default_rng(5)
    for i in range(N):
        rgb = rng.random((H, W, 3)).astype(np.float32)
        codec, pix, opts = plateio.still_target({"ext": ".png", "pix_fmt": "rgb48be"}, False)
        open(os.path.join(png, f"plate.{1001 + i}.png"), "wb").write(plateio.encode_still(rgb, None, codec, pix, opts))
    return {"exr": ("paintaplate_test/exr", "linear"), "mov": ("paintaplate_test/plate.mov", "sRGB"),
            "png16": ("paintaplate_test/png16", "sRGB")}


def fake_shot_and_matte(out_dir, run):
    """What `shot` and `matte` would write: sRGB frames at half size, and a mask of the edit."""
    sw, sh = W // 2, H // 2 + (H // 2) % 2
    base = os.path.join(out_dir, "paintaplate_test", run)
    for sub in ("shot", "matte_a"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    for i in range(plateio.pad_count_8n1(N)):
        frame = np.full((sh, sw, 3), 0.5, np.float32); frame[10:30, 20:60] = [1.0, 0.3, 0.1]
        m = np.zeros((sh, sw, 3), np.float32); m[10:30, 20:60] = 1.0
        for sub, img in (("shot", frame), ("matte_a", m)):
            codec, pix, opts = plateio.still_target({"ext": ".png"}, False)
            open(os.path.join(base, sub, f"f_{i + 1:05d}_.png"), "wb").write(plateio.encode_still(img, None, codec, pix, opts))
    return f"paintaplate_test/{run}"


def verify_export(kind, plate_dir, out_dir, relight):
    files = sorted(os.listdir(out_dir))
    check(len(files) >= 1, f"{kind}: export wrote {len(files)} file(s)")
    if kind == "exr":
        src = plateio.find_sequence(plate_dir)
        check(len(files) == N and files[0] == os.path.basename(src[0]), f"exr: {N} frames, first named {files[0] if files else '-'}")
        with OpenEXR.File(src[3], separate_channels=True) as a, OpenEXR.File(os.path.join(out_dir, files[3]), separate_channels=True) as b:
            ca, cb = a.channels(), b.channels()
            check(set(ca) == set(cb), "exr: same channel set (extra layers kept)")
            extra_same = all(np.array_equal(ca[c].pixels, cb[c].pixels) for c in ca if c not in "RGB")
            check(extra_same, "exr: extra layers bit-identical")
            outside = np.zeros((H, W), bool); outside[92:, :] = True; outside[:, 160:] = True  # far beyond grow + feather
            same_out = all(np.array_equal(ca[c].pixels[outside], cb[c].pixels[outside]) for c in "RGB")
            if relight:
                check(not np.array_equal(ca["R"].pixels, cb["R"].pixels), "exr relight: every pixel may change")
            else:
                check(same_out, "exr: pixels outside the edit bit-identical")
                check(not np.array_equal(ca["R"].pixels[25:35, 50:100], cb["R"].pixels[25:35, 50:100]), "exr: pixels inside the edit changed")
            check(str(b.header()["compression"]) == str(a.header()["compression"]), "exr: compression kept")
    elif kind == "mov":
        spec_in = plateio.probe_plate(plate_dir); spec_out = plateio.probe_plate(os.path.join(out_dir, files[0]))
        for k in ("codec", "pix_fmt", "width", "height", "fps_num", "fps_den", "timecode", "audio_streams", "colorspace"):
            check(spec_in[k] == spec_out[k], f"mov: {k} kept ({spec_out[k]})")
    elif kind == "png16":
        src = plateio.find_sequence(plate_dir)
        a = plateio.read_native(src[2], False); b = plateio.read_native(os.path.join(out_dir, files[2]), False)
        outside = np.zeros((H, W), bool); outside[92:, :] = True; outside[:, 160:] = True
        check(np.array_equal(a[outside], b[outside]), "png16: pixels outside the edit bit-identical (exact 16-bit read)")
        check(len(files) == N, f"png16: {N} frames")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy", required=True); ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--url", default=""); ap.add_argument("--port", type=int, default=8188)
    a = ap.parse_args()
    url = a.url or f"http://127.0.0.1:{a.port}"
    proc = None
    if not a.url:
        log = open("/tmp/comfy_live.log", "w")
        proc = subprocess.Popen([a.python, "main.py", "--cpu", "--listen", "127.0.0.1", "--port", str(a.port),
                                 "--disable-auto-launch", "--preview-method", "none"], cwd=a.comfy, stdout=log, stderr=subprocess.STDOUT)
    try:
        t0 = time.time()
        while True:
            try:
                http(f"{url}/system_stats", timeout=3); break
            except Exception:
                if time.time() - t0 > 150 or (proc and proc.poll() is not None):
                    print(open("/tmp/comfy_live.log").read()[-3000:]); raise SystemExit("ComfyUI did not start")
                time.sleep(1)
        print(f"ComfyUI up in {time.time() - t0:.0f} s")
        log_text = open("/tmp/comfy_live.log").read() if proc else ""
        check("IMPORT FAILED" not in log_text or "ainvfx-paintaplate" not in log_text.split("IMPORT FAILED")[-1][:200], "pack imports without error")

        print("1. Nodes and page")
        for cls in ["PaintAPlate_LoadPlate", "PaintAPlate_SavePlate", "PaintAPlate_FitToPlate", "PaintAPlate_RelightTransfer",
                    "LTXAddVideoICLoRAGuide", "SAM3_VideoTrack", "ReferenceMultiLatent", "ImageColorSpace"]:
            info, _ = http(f"{url}/object_info/{cls}")
            check(cls in info, f"node {cls} registered")
        page, ctype = http(f"{url}/extensions/ainvfx-paintaplate/paintaplate.html")
        check(b"PaintAPlate" in page, "app page served")
        _, ctype = http(f"{url}/extensions/ainvfx-paintaplate/app.mjs")
        check("javascript" in ctype, f"app.mjs served as JavaScript ({ctype})")
        exts, _ = http(f"{url}/extensions")
        check(any(e.endswith("ainvfx-paintaplate/open.js") for e in exts) and not any(e.endswith("app.mjs") for e in exts),
              "only open.js loads into the graph editor")

        stats, _ = http(f"{url}/system_stats")
        comfy_root = a.comfy
        input_dir, output_dir = os.path.join(comfy_root, "input"), os.path.join(comfy_root, "output")
        plates = make_plates(input_dir)
        for name, blob in (("base.png", "gray"), ("mask.png", "mask")):
            img = np.full((432, 768, 3), 0.5, np.float32)
            if blob == "mask":
                img[:] = 0; img[100:200, 200:400] = 1
            codec, pix, opts = plateio.still_target({"ext": ".png"}, False)
            http(f"{url}/upload/image", {"subfolder": "paintaplate/test", "overwrite": "true"},
                 {"image": (name, plateio.encode_still(img, None, codec, pix, opts))})

        print("2. ComfyUI's validator accepts every workflow")
        values = {
            "ingest": {"path": plates["exr"][0], "color_space": "linear", "prefix": "paintaplate_test/hero", "video_prefix": "paintaplate_test/proxy"},
            "edit": {"base": "paintaplate/test/base.png", "reference": "paintaplate/test/base.png", "start": "paintaplate/test/base.png",
                     "mask": "paintaplate/test/mask.png", "caption": 'Remove <obj_1>. [{"id": "obj_1", "bbox": [100, 200, 300, 500], "desc": "x"}]',
                     "seed": 1, "steps": 8, "denoise": 1.0, "grow": 16, "feather": 6, "sigma": 3},
            "shot": {"path": plates["exr"][0], "color_space": "linear", "max_frames": N, "hero": "paintaplate/test/base.png", "width": 96, "height": 64,
                     "seed": 1, "prefix": "paintaplate_test/shot/f", "video_prefix": "paintaplate_test/shotpreview"},
            "snap": {"image": "paintaplate/test/base.png", "points": '[{"x": 40, "y": 30}]'},
            "matte": {"path": plates["exr"][0], "color_space": "linear", "max_frames": N, "mask": "paintaplate/test/mask.png", "width": 96, "height": 64,
                      "prefix": "paintaplate_test/matte/m"},
        }
        for name in ("edit", "snap", "shot", "matte"):  # model workflows: validate, then cancel
            res = submit(url, fill(name, values[name])["prompt"])
            ok = "prompt_id" in res
            check(ok, f"{name}: accepted" + ("" if ok else f" -> {json.dumps(res.get('node_errors') or res.get('error'))[:600]}"))
            if ok:
                http(f"{url}/queue", {"delete": [res["prompt_id"]]}); http(f"{url}/interrupt", {"prompt_id": res["prompt_id"]})
                wait(url, res["prompt_id"], 60)

        print("3. ingest and export, end to end")
        for kind, (path, cs) in plates.items():
            res = submit(url, fill("ingest", {**values["ingest"], "path": path, "color_space": cs,
                                              "prefix": f"paintaplate_test/{kind}/hero", "video_prefix": f"paintaplate_test/{kind}/proxy"})["prompt"])
            if "prompt_id" not in res:
                check(False, f"ingest {kind}: rejected {json.dumps(res)[:500]}"); continue
            entry, dt = wait(url, res["prompt_id"])
            err = error_of(entry) if entry else "timeout"
            check(entry is not None and not err, f"ingest {kind}: ran in {dt:.1f} s" + (f" -> {err}" if err else ""))
            if entry and not err:
                outs = entry["outputs"]
                found = [f for o in outs.values() for key in ("images", "gifs", "video") for f in o.get(key, [])]
                keys = sorted({key for o in outs.values() for key in o})
                check(any(f["filename"].endswith(".png") for f in found), f"ingest {kind}: hero PNG ({keys})")
                check(any(f["filename"].endswith((".mp4", ".webm")) for f in found), f"ingest {kind}: playback proxy video")
                texts = [t for o in outs.values() for t in o.get("text", [])]
                spec = json.loads(texts[0]) if texts else {}
                check(spec.get("frames") == N and spec.get("width") == W, f"ingest {kind}: spec {spec.get('kind')}, {spec.get('width')}x{spec.get('height')}, {spec.get('frames')} frames, guess {spec.get('color_space_guess')}")
            for relight in (False, True) if kind == "exr" else (False,):
                run = f"{kind}_r{int(relight)}"
                shot = fake_shot_and_matte(output_dir, run)
                exp_dir = f"paintaplate_test/{run}/export"
                shutil.rmtree(os.path.join(output_dir, exp_dir), ignore_errors=True)
                res = submit(url, fill("export", {"path": path, "color_space": cs, "max_frames": N, "shot": f"output:{shot}/shot",
                                                  "matte_a": f"output:{shot}/matte_a", "matte_b": f"output:{shot}/matte_a",
                                                  "relight": relight, "keep_untouched": not relight, "prefix": exp_dir})["prompt"])
                if "prompt_id" not in res:
                    check(False, f"export {run}: rejected {json.dumps(res)[:600]}"); continue
                entry, dt = wait(url, res["prompt_id"])
                err = error_of(entry) if entry else "timeout"
                check(entry is not None and not err, f"export {run}: ran in {dt:.1f} s" + (f" -> {err}" if err else ""))
                if entry and not err:
                    verify_export(kind, os.path.join(input_dir, path), os.path.join(output_dir, exp_dir), relight)
    finally:
        if proc:
            proc.terminate(); proc.wait(20)
    print("\nALL PASSED" if not FAILS else f"\n{len(FAILS)} FAILED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
