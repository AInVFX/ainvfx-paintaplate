"""Drive the real page in headless Chromium against a real ComfyUI, without models.

    python tests/ui_live.py --comfy /path/to/ComfyUI --python /path/to/python

The pack is copied to a temporary folder where `edit`, `shot` and `matte` are
replaced by stand-ins built from core nodes only (same slots, no models), so
the whole flow runs on a CPU: open a plate, paint, erase and light, pick
options, let the idle time render the shot, mattes and export. `ingest` and
`export` are the real workflows. Screenshots go to /tmp/paintaplate_ui.
"""
import argparse, glob, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [REPO, HERE, os.path.join(REPO, "tools")]
import comfy_live  # noqa: E402
from build_workflows import Graph, Slot, plate  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = "/tmp/paintaplate_ui"


def stand_ins(out):
    g = Graph()  # edit: the reference inverted inside the grown mask, composited over the base
    base, ref = g("LoadImage", image=Slot("base", "")), g("LoadImage", image=Slot("reference", ""))
    g("LoadImage", image=Slot("start", ""))
    grown = g("GrowMask", mask=g("LoadImageMask", image=Slot("mask", ""), channel="red"), expand=Slot("grow", 8), tapered_corners=True)
    g("PreviewImage", images=g("ImageCompositeMasked", destination=base, source=g("ImageInvert", image=ref), x=0, y=0,
                                resize_source=False, mask=grown))
    g.save_to(out, "edit")

    g = Graph()  # shot: the Ripple reference itself (hero frame + plate frames), saved like the real one
    load, srgb = plate(g, pad=True)
    frames = g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 96), height=Slot("height", 64), crop="disabled")
    size = g("GetImageSize", image=frames)
    hero = g("ImageScale", image=g("LoadImage", image=Slot("hero", "")), upscale_method="area", width=size[0], height=size[1], crop="disabled")
    ref = g("BatchImagesNode", images__image0=hero, images__image1=g("ImageFromBatch", image=frames, batch_index=1, length=4096))
    g("SaveImage", images=ref, filename_prefix=Slot("prefix", "x/f"))
    g("SaveVideo", video=g("CreateVideo", images=ref, fps=load[3], bit_depth=8, color_space="sRGB", codec="none"),
      filename_prefix=Slot("video_prefix", "x/v"), format="auto", format__codec="auto")
    g.save_to(out, "shot")

    g = Graph()  # matte: the first-frame mask repeated over every frame
    _, srgb = plate(g, pad=True)
    size = g("GetImageSize", image=g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 96),
                                     height=Slot("height", 64), crop="disabled"))
    m = g("ImageScale", image=g("MaskToImage", mask=g("LoadImageMask", image=Slot("mask", ""), channel="red")),
          upscale_method="area", width=size[0], height=size[1], crop="disabled")
    g("SaveImage", images=g("RepeatImageBatch", image=m, amount=size[2]), filename_prefix=Slot("prefix", "x/m"))
    g.save_to(out, "matte")

    g = Graph()  # snap: no object found, the page keeps the painted stroke
    g("LoadImage", image=Slot("image", "")); g("PrimitiveString", value=Slot("points", "[]"))
    g("PreviewImage", images=g("MaskToImage", mask=g("SolidMask", value=0.0, width=64, height=64)))
    g.save_to(out, "snap")


def stroke(page, box, pts):
    page.mouse.move(box["x"] + pts[0][0] * box["width"], box["y"] + pts[0][1] * box["height"])
    page.mouse.down()
    for x, y in pts[1:]:
        page.mouse.move(box["x"] + x * box["width"], box["y"] + y * box["height"], steps=6)
    page.mouse.up()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy", required=True); ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--port", type=int, default=8190)
    ap.add_argument("--url", default="", help="a running ComfyUI with the real workflows and models (no stand-ins)")
    ap.add_argument("--path", default="", help="plate path in that ComfyUI's input folder, typed into the open dialog")
    ap.add_argument("--cs", default="linear")
    ap.add_argument("--strokes", default="", help='JSON list of [key, words, [[x, y], ...], pick]')
    ap.add_argument("--timeout", type=int, default=150)
    ap.add_argument("--out", default=SHOTS, help="folder for screenshots and timings")
    ap.add_argument("--think", type=float, default=0, help="seconds between opening the plate and the first stroke")
    a = ap.parse_args()
    if a.url:
        return remote(a)
    temp = "/tmp/paintaplate_dry"
    shutil.rmtree(temp, ignore_errors=True)
    shutil.copytree(REPO, temp, ignore=shutil.ignore_patterns("__pycache__", ".git", "tests"))
    Graph.save_to = lambda self, out, name: (os.makedirs(out, exist_ok=True), __import__("json").dump(
        {"prompt": self.prompt, "slots": self.slots}, open(os.path.join(out, f"{name}.json"), "w"), indent=1))
    stand_ins(os.path.join(temp, "web", "workflows"))
    link = os.path.join(a.comfy, "custom_nodes", "ainvfx-paintaplate")
    real = os.readlink(link) if os.path.islink(link) else None
    if os.path.islink(link):
        os.remove(link)
    os.symlink(temp, link)
    plates = comfy_live.make_plates(os.path.join(a.comfy, "input"))
    exr = sorted(glob.glob(os.path.join(a.comfy, "input", plates["exr"][0], "*.exr")))
    shutil.rmtree(SHOTS, ignore_errors=True); os.makedirs(SHOTS)
    log = open("/tmp/ui_live.log", "w")
    proc = subprocess.Popen([a.python, "main.py", "--cpu", "--listen", "127.0.0.1", "--port", str(a.port),
                             "--disable-auto-launch", "--preview-method", "latent2rgb"], cwd=a.comfy, stdout=log, stderr=subprocess.STDOUT)
    errors, ok, final = [], False, ""
    try:
        url = f"http://127.0.0.1:{a.port}"
        t0 = time.time()
        while True:
            try:
                comfy_live.http(f"{url}/system_stats", timeout=3); break
            except Exception:
                if time.time() - t0 > 150:
                    raise SystemExit("ComfyUI did not start")
                time.sleep(1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("console", lambda m: (m.type == "error" and errors.append(m.text), print("   [console]", m.type, m.text[:200])))
            page.on("pageerror", lambda e: errors.append(str(e)))
            status = lambda: page.inner_text("#status")  # noqa: E731
            page.goto(f"{url}/extensions/ainvfx-paintaplate/paintaplate.html")
            page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=30000)
            page.screenshot(path=f"{SHOTS}/1_empty.png")
            page.click("#open-btn")
            page.set_input_files("#files", exr)
            page.select_option("#cs", "linear")
            page.click("#open-go")
            page.wait_for_function("document.querySelector('#empty').hidden", timeout=90000)
            try:
                print("opened:", status(), "|", page.inner_text("#spec"))
                box = page.locator("#view").bounding_box()
                for key, words, pts, pick in (("b", "a fire", [(0.3, 0.6), (0.4, 0.5), (0.45, 0.65)], "1"),
                                              ("e", "", [(0.7, 0.3), (0.75, 0.4)], "2"),
                                              ("l", "warm sunset", [(0.1, 0.1), (0.2, 0.15)], "1")):
                    page.keyboard.press(key)
                    page.fill("#prompt", words)
                    stroke(page, box, pts)
                    page.wait_for_function("document.querySelectorAll('.option.ready').length === 2", timeout=60000)
                    page.screenshot(path=f"{SHOTS}/2_{key}_options.png")
                    n = page.locator("#stack li").count()
                    page.keyboard.press(pick)
                    page.wait_for_function(f"document.querySelectorAll('#stack li').length === {n + 1}", timeout=60000)
                    print(f"edit {key}: committed |", status())
                page.wait_for_function("document.querySelector('#status').textContent.startsWith('Exported')", timeout=150000)
                page.screenshot(path=f"{SHOTS}/3_exported.png")
                final = status()
                print("final:", final)
            except Exception:  # read the page while it is still open
                print("status:", status())
                print("tiles:", page.evaluate("[...document.querySelectorAll('.option')].map(b => b.className + ' ' + (b.querySelector('img').getAttribute('src') || '-').slice(0, 40))"))
                page.screenshot(path=f"{SHOTS}/fail.png")
                raise
            ok = True
            browser.close()
    except Exception as exc:
        print("FAILED AT:", type(exc).__name__, str(exc).splitlines()[0][:200])
        try:
            print("status:", status())
            print("tiles:", page.evaluate("[...document.querySelectorAll('.option')].map(b => b.className + ' ' + (b.querySelector('img').getAttribute('src') || '-').slice(0, 60))"))
            page.screenshot(path=f"{SHOTS}/fail.png")
        except Exception as e2:
            print("diag failed:", e2)
    finally:
        proc.terminate(); proc.wait(20)
        os.remove(link)
        if real:
            os.symlink(real, link)
    folder = final.split(" in ", 1)[1].strip() if " in " in final else ""  # "Exported: 17 file(s) in <folder>"
    exports = glob.glob(os.path.join(folder, "*.exr")) if folder else []
    print(f"export files: {len(exports)}; console errors: {len(errors)}")
    for e in errors[:10]:
        print("  console:", e[:300])
    print("UI FLOW PASSED" if ok and exports and not errors else "UI FLOW FAILED")
    return 0 if ok and exports and not errors else 1


def remote(a):
    """The real page, workflows and models on a remote ComfyUI: timings for each stage."""
    import json
    shots = a.out
    shutil.rmtree(shots, ignore_errors=True); os.makedirs(shots)
    strokes = json.loads(a.strokes) if a.strokes else [["b", "a small campfire", [[0.45, 0.8], [0.5, 0.75], [0.55, 0.8]], "1"]]
    marks, errors, t0 = [], [], time.time()
    mark = lambda what: (marks.append((round(time.time() - t0, 1), what)), print(f"{marks[-1][0]:7.1f} s  {what}"))  # noqa: E731
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        status = lambda: page.inner_text("#status")  # noqa: E731
        try:
            page.goto(f"{a.url}/extensions/ainvfx-paintaplate/paintaplate.html")
            page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
            mark("page ready: " + status())
            page.click("#open-btn"); page.fill("#path", a.path)
            if a.cs:
                page.select_option("#cs", a.cs)
            page.click("#open-go")
            page.wait_for_function("document.querySelector('#empty').hidden", timeout=300000)
            mark("plate open: " + page.inner_text("#spec")); page.screenshot(path=f"{shots}/1_open.png")
            box = page.locator("#view").bounding_box()
            page.wait_for_timeout(a.think * 1000)  # a person looks at the frame before painting
            for key, words, pts, pick, *size in strokes:
                page.keyboard.press(key); page.fill("#prompt", words)
                if size:  # brush size in frame pixels, set on the slider
                    page.eval_on_selector("#size", "(el, v) => { el.value = v; el.dispatchEvent(new Event('input')); }", size[0])
                stroke(page, box, pts); mark(f"{key} stroke")
                page.wait_for_function("[...document.querySelectorAll('.option img')].some(i => i.src)", timeout=120000)
                mark(f"{key} first image in a tile")
                page.wait_for_function("document.querySelectorAll('.option.ready').length === 2", timeout=180000)
                mark(f"{key} both options ready"); page.screenshot(path=f"{shots}/2_{key}_options.png")
                n = page.locator("#stack li").count(); page.keyboard.press(pick)
                page.wait_for_function(f"document.querySelectorAll('#stack li').length === {n + 1}", timeout=240000)
                mark(f"{key} committed"); page.screenshot(path=f"{shots}/3_{key}_committed.png")
            seen = set()
            deadline = time.time() + a.timeout * 6
            while time.time() < deadline:
                st = status()
                tag = st.split(",")[0]
                if tag not in seen:
                    seen.add(tag); mark("status: " + st)
                if st.startswith("Exported") or "Error" in st or ":" in tag and "Exported" not in st and "ready" not in st and "Missing" in st:
                    break
                time.sleep(1)
            page.click("#view-shot"); time.sleep(2); page.screenshot(path=f"{shots}/4_shot.png")
        except Exception as exc:
            mark(f"FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:160]} | status: {status()}")
            page.screenshot(path=f"{shots}/fail.png")
        browser.close()
    json.dump({"marks": marks, "errors": errors}, open(f"{shots}/timings.json", "w"), indent=1)
    print("console errors:", errors[:5])
    return 0


if __name__ == "__main__":
    sys.exit(main())
