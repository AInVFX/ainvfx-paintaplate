"""Drive the real page in headless Chromium against a real ComfyUI, without models.

    python tests/ui_live.py --comfy /path/to/ComfyUI --python /path/to/python

The pack is copied to a temporary folder where `edit`, `snap`, `shot` and `matte` are replaced by
stand-ins built from core nodes only (same slots and outputs, no models), so the whole flow runs on a
CPU: open a plate, play it, paint, erase and light, let each edit start by itself, bypass and bring back
an edit, let the idle time render the shot, the composite and the export, wipe, then download the zip.
`ingest`, `comp` and `export` are the real workflows. Screenshots go to /tmp/paintaplate_ui.
"""
import argparse, glob, json, os, shutil, subprocess, sys, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [REPO, HERE, os.path.join(REPO, "tools")]
import comfy_live  # noqa: E402
from build_workflows import Graph, Slot, plate  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = "/tmp/paintaplate_ui"


def stand_ins(out):
    g = Graph()  # edit: the reference inverted inside the grown mask; the patch is the same with the mask as alpha
    base, ref = g("LoadImage", image=Slot("base", "")), g("LoadImage", image=Slot("reference", ""))
    g("LoadImage", image=Slot("start", ""))
    grown = g("GrowMask", mask=g("LoadImageMask", image=Slot("mask", ""), channel="red"), expand=Slot("grow", 8), tapered_corners=True)
    inv = g("ImageInvert", image=ref)
    g("PreviewImage", _output="result", images=g("ImageCompositeMasked", destination=base, source=inv, x=0, y=0,
                                                   resize_source=False, mask=grown))
    g("PreviewImage", _output="patch", images=g("JoinImageWithAlpha", image=inv, alpha=g("InvertMask", mask=grown)))
    g.save("edit", out)

    g = Graph()  # shot: the Ripple reference itself (hero frame + plate frames), saved like the real one
    load, srgb = plate(g, pad=True)
    frames = g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 96), height=Slot("height", 64), crop="disabled")
    size = g("GetImageSize", image=frames)
    hero = g("ImageScale", image=g("LoadImage", image=Slot("hero", "")), upscale_method="area", width=size[0], height=size[1], crop="disabled")
    ref = g("BatchImagesNode", images__image0=hero, images__image1=g("ImageFromBatch", image=frames, batch_index=1, length=4096))
    g("SaveImage", _output="frames", images=ref, filename_prefix=Slot("prefix", "x/f"))
    g("SaveVideo", _output="video", video=g("CreateVideo", images=ref, fps=load[3], bit_depth=8, color_space="sRGB", codec="none"),
      filename_prefix=Slot("video_prefix", "x/v"), format="auto", format__codec="auto")
    g.save("shot", out)

    g = Graph()  # matte: the first-frame mask repeated over every frame
    _, srgb = plate(g, pad=True)
    size = g("GetImageSize", image=g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 96),
                                     height=Slot("height", 64), crop="disabled"))
    m = g("ImageScale", image=g("MaskToImage", mask=g("LoadImageMask", image=Slot("mask", ""), channel="red")),
          upscale_method="area", width=size[0], height=size[1], crop="disabled")
    g("SaveImage", _output="frames", images=g("RepeatImageBatch", image=m, amount=size[2]), filename_prefix=Slot("prefix", "x/m"))
    g.save("matte", out)

    g = Graph()  # snap: no object found, the page keeps the painted stroke
    g("LoadImage", image=Slot("image", "")); g("PrimitiveString", value=Slot("points", "[]"))
    g("PreviewImage", _output="mask", images=g("MaskToImage", mask=g("SolidMask", value=0.0, width=64, height=64)))
    g.save("snap", out)


def stroke(page, box, pts):
    page.mouse.move(box["x"] + pts[0][0] * box["width"], box["y"] + pts[0][1] * box["height"])
    page.mouse.down()
    for x, y in pts[1:]:
        page.mouse.move(box["x"] + x * box["width"], box["y"] + y * box["height"], steps=6)
    page.mouse.up()


DONE = "document.querySelectorAll('#history li').length === {n} && !document.querySelector('#history li.busy')"


def flow(page, url, open_plate, shots, wait_s=120):
    """The flow both runs share: the page must already show 'Ready'."""
    status = lambda: page.inner_text("#status")  # noqa: E731
    open_plate()
    page.wait_for_function("document.querySelector('#empty').hidden", timeout=wait_s * 1000)
    print("opened:", status(), "|", page.inner_text("#spec"))
    page.keyboard.press("Space"); page.wait_for_timeout(600); page.keyboard.press("Space")  # play, then pause
    playing_frame = page.inner_text("#frame-now")
    page.keyboard.press("Home")
    box = page.locator("#view").bounding_box()
    for i, (key, words, pts) in enumerate((("b", "a fire", [(0.3, 0.6), (0.4, 0.5), (0.45, 0.65)]),
                                           ("e", "", [(0.7, 0.3), (0.75, 0.4)]),
                                           ("l", "warm sunset", [(0.1, 0.1), (0.2, 0.15)]))):
        page.keyboard.press(key)
        page.fill("#prompt", words)
        page.locator("#prompt").blur()
        stroke(page, box, pts)  # the edit starts by itself once the strokes stop
        page.wait_for_function(DONE.format(n=i + 1), timeout=wait_s * 1000)
        page.screenshot(path=f"{shots}/2_{key}_done.png")
        print(f"edit {key}: done |", status())
    page.locator("#history li").nth(1).locator(".eye").click()  # bypass the erase, then bring it back
    page.wait_for_function("document.querySelectorAll('#history li.off').length === 1 && !document.querySelector('#history li.busy')",
                           timeout=wait_s * 1000)
    page.locator("#history li").nth(1).locator(".eye").click()
    page.wait_for_function("!document.querySelector('#history li.off') && !document.querySelector('#history li.busy')", timeout=wait_s * 1000)
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Exported')", timeout=wait_s * 3000)
    page.keyboard.press("F6")  # wipe on, at frame 10
    page.keyboard.press("End")
    page.screenshot(path=f"{shots}/3_exported_wipe.png")
    final = status()
    print("final:", final, "| frame while playing:", playing_frame)
    with page.expect_download(timeout=wait_s * 1000) as dl:
        page.click("#export-btn")
    path = f"{shots}/download.zip"
    dl.value.save_as(path)
    names = zipfile.ZipFile(path).namelist()
    print("zip:", len(names), "files;", sorted({n.split("/")[0] for n in names}))
    return final, names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy", required=True); ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--port", type=int, default=8190)
    ap.add_argument("--url", default="", help="a running ComfyUI with the real workflows and models (no stand-ins)")
    ap.add_argument("--path", default="", help="plate path in that ComfyUI's input folder, typed into the open dialog")
    ap.add_argument("--cs", default="linear")
    ap.add_argument("--strokes", default="", help='JSON list of [key, words, [[x, y], ...], brush size]')
    ap.add_argument("--timeout", type=int, default=150)
    ap.add_argument("--out", default=SHOTS, help="folder for screenshots and timings")
    ap.add_argument("--think", type=float, default=0, help="seconds between opening the plate and the first stroke")
    ap.add_argument("--channel", default="", help="a browser channel, such as chrome (it plays H.264; Playwright's Chromium does not)")
    a = ap.parse_args()
    if a.url:
        return remote(a)
    temp = "/tmp/paintaplate_dry"
    shutil.rmtree(temp, ignore_errors=True)
    shutil.copytree(REPO, temp, ignore=shutil.ignore_patterns("__pycache__", ".git", "tests"))
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
    errors, ok, names = [], False, []
    page = None
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
            page = browser.new_page(viewport={"width": 1280, "height": 800}, accept_downloads=True)
            page.on("console", lambda m: (m.type == "error" and errors.append(m.text), print("   [console]", m.type, m.text[:200])))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{url}/extensions/ainvfx-paintaplate/paintaplate.html?wait=400")
            page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=30000)
            page.screenshot(path=f"{SHOTS}/1_empty.png")

            def open_plate():
                page.click("#open-btn")
                page.set_input_files("#files", exr)
                page.select_option("#cs", "linear")
                page.click("#open-go")
            try:
                final, names = flow(page, url, open_plate, SHOTS)
            except Exception:
                print("status:", page.inner_text("#status"))
                page.screenshot(path=f"{SHOTS}/fail.png")
                raise
            ok = final.startswith("Exported")
            browser.close()
    except Exception as exc:
        print("FAILED AT:", type(exc).__name__, str(exc).splitlines()[0][:200])
    finally:
        proc.terminate(); proc.wait(20)
        os.remove(link)
        if real:
            os.symlink(real, link)
    exports = [n for n in names if n.startswith("export/") and n.endswith(".exr")]
    mattes = [n for n in names if n.startswith("matte/")]
    print(f"zip: {len(exports)} EXR frames, {len(mattes)} matte frames; console errors: {len(errors)}")
    for e in errors[:10]:
        print("  console:", e[:300])
    passed = ok and exports and mattes and not errors
    print("UI FLOW PASSED" if passed else "UI FLOW FAILED")
    return 0 if passed else 1


def remote(a):
    """The real page, workflows and models on a remote ComfyUI: a timed mark for every stage."""
    shots = a.out
    shutil.rmtree(shots, ignore_errors=True); os.makedirs(shots)
    strokes = json.loads(a.strokes) if a.strokes else [["b", "a small campfire", [[0.45, 0.8], [0.5, 0.75], [0.55, 0.8]]]]
    marks, errors, t0 = [], [], time.time()
    mark = lambda what: (marks.append((round(time.time() - t0, 1), what)), print(f"{marks[-1][0]:7.1f} s  {what}"))  # noqa: E731
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=a.channel or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
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
            for i, (key, words, pts, *size) in enumerate(strokes):
                page.keyboard.press(key); page.fill("#prompt", words); page.locator("#prompt").blur()
                if size:  # brush size in frame pixels, set on the slider
                    page.eval_on_selector("#size", "(el, v) => { el.value = v; el.dispatchEvent(new Event('input')); }", size[0])
                stroke(page, box, pts); mark(f"{key} stroke")
                page.wait_for_function("document.querySelector('#history li.busy .state')", timeout=60000)
                page.wait_for_function(DONE.format(n=i + 1), timeout=300000)
                mark(f"{key} edit on the first frame | {status()}"); page.screenshot(path=f"{shots}/2_{key}_done.png")
            seen = set()
            deadline = time.time() + a.timeout * 8
            while time.time() < deadline:
                note = page.inner_text("#render-note")
                tag = note.rsplit(" ", 1)[0] if note else status()[:40]
                if tag not in seen:
                    seen.add(tag); mark("stage: " + (note or status()))
                if status().startswith("Exported") or "Error" in status() or status().startswith("Missing"):
                    break
                time.sleep(1)
            mark("final: " + status())
            page.keyboard.press("F6"); page.keyboard.press("End"); time.sleep(1); page.screenshot(path=f"{shots}/3_wipe.png")
            page.keyboard.press("F6"); page.keyboard.press("Home"); page.keyboard.press("Space"); time.sleep(2)
            page.keyboard.press("Space"); page.screenshot(path=f"{shots}/4_played.png")
            if status().startswith("Exported"):
                with page.expect_download(timeout=600000) as dl:
                    page.click("#export-btn")
                dl.value.save_as(f"{shots}/export.zip")
                mark(f"downloaded {len(zipfile.ZipFile(f'{shots}/export.zip').namelist())} files")
        except Exception as exc:
            mark(f"FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:160]} | status: {status()}")
            page.screenshot(path=f"{shots}/fail.png")
        browser.close()
    json.dump({"marks": marks, "errors": errors}, open(f"{shots}/timings.json", "w"), indent=1)
    print("console errors:", errors[:5])
    return 0


if __name__ == "__main__":
    sys.exit(main())
