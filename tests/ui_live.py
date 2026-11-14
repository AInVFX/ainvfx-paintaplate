"""Drive the real page in headless Chromium against a real ComfyUI, without models.

    python tests/ui_live.py --comfy /path/to/ComfyUI --python /path/to/python

The pack is copied to a temporary folder where `edit`, `snap`, `shot` and `matte` are replaced by
stand-ins built from core nodes only (same slots and outputs, no models), so the whole flow runs on a
CPU: open a plate, play it, paint, erase and light, start each edit with Generate (Enter), bypass and bring back
an edit, let the idle time render the shot, the composite and the export, wipe, then download the zip.
`ingest`, `comp` and `export` are the real workflows. Screenshots go to /tmp/paintaplate_ui.
"""
import argparse, glob, json, os, shutil, subprocess, sys, time, urllib.request, zipfile

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
    # saved in the output folder, as the real edit saves them: the job index keeps the stand-in's jobs as it keeps Klein's
    g("SaveImage", _output="result", images=g("ImageCompositeMasked", destination=base, source=inv, x=0, y=0,
                                                resize_source=False, mask=grown), filename_prefix=Slot("prefix", "x/e"))
    g("SaveImage", _output="patch", images=g("JoinImageWithAlpha", image=inv, alpha=g("InvertMask", mask=grown)),
      filename_prefix=Slot("prefix", "x/e"))
    g("SaveImage", _output="relit", images=inv, filename_prefix=Slot("prefix", "x/e"))
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
    g.save("clean", out)  # the erase pass: the same stand-in, saved under its name

    g = Graph()  # matte: the first-frame mask repeated over every frame
    _, srgb = plate(g, pad=True)
    size = g("GetImageSize", image=g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 96),
                                     height=Slot("height", 64), crop="disabled"))
    m = g("ImageScale", image=g("MaskToImage", mask=g("LoadImageMask", image=Slot("mask", ""), channel="red")),
          upscale_method="area", width=size[0], height=size[1], crop="disabled")
    g("SaveImage", _output="frames", images=g("RepeatImageBatch", image=m, amount=size[2]), filename_prefix=Slot("prefix", "x/m"))
    g.save("matte", out)

    g = Graph()  # snap: no object at any point and none by name, the page keeps the painted stroke
    g("LoadImage", image=Slot("image", "")); g("PrimitiveString", value=Slot("words", ""))
    empty = g("MaskToImage", mask=g("SolidMask", value=0.0, width=64, height=64))
    for k in range(5):
        g("PrimitiveString", value=Slot(f"point_{k}", "[]")); g("PreviewImage", _output=f"point_{k}", images=empty)
    g("PreviewImage", _output="named", images=empty)
    g.save("snap", out)

    g = Graph()  # prompt: the request comes back as the caption (it ends with the locked rows, as an answer would)
    g("LoadImage", image=Slot("image", "")); g("PrimitiveStringMultiline", value=Slot("system", ""))
    g("PreviewAny", _output="text", source=g("PrimitiveStringMultiline", value=Slot("request", "")))
    g.save("prompt", out)


def executing(events, t0):
    """A listener for the page's WebSocket that keeps each « executing » message of ComfyUI, with the seconds since t0 when it
    arrived: when each node started. gpu_matrix.py makes each node's seconds of them (node_times). Previews are binary."""
    def heard(payload):
        if isinstance(payload, str) and '"executing"' in payload:
            try:
                msg = json.loads(payload)
            except ValueError:
                return
            if msg.get("type") == "executing":
                data = msg.get("data") or {}
                events.append([round(time.time() - t0, 3), data.get("prompt_id"), data.get("node")])
    return lambda ws: ws.on("framereceived", heard)


def deliver_hdr(page):
    """--hdr: SDR to HDR on for this run, before any edit, as a render's key holds the switch. On a plate whose format holds
    nothing above 1.0, Deliver's switch asks to confirm; an EXR plate that holds values above 1.0 runs it on its own."""
    if page.is_visible("#deliver-auto"):
        return "SDR to HDR: on its own for this plate"
    if not page.is_visible("#deliver-hdr"):
        raise RuntimeError("--hdr: Deliver offers no SDR to HDR on this page (?hdr=0, or its model files or nodes are missing)")
    page.click("#deliver-hdr")
    if page.is_visible("#deliver-confirm"):
        page.click("#deliver-yes")
    page.wait_for_function("document.querySelector('#deliver-hdr').checked", timeout=10000)
    return "SDR to HDR: on, asked for by --hdr"


def pick(page, tool):
    """Pick a tool by its button, as a person clicks it: its data-tool (paint, erase, light) stays when a label or a key changes."""
    page.click(f'.tools [data-tool="{tool}"]')


def stroke(page, box, pts):
    page.mouse.move(box["x"] + pts[0][0] * box["width"], box["y"] + pts[0][1] * box["height"])
    page.mouse.down()
    for x, y in pts[1:]:
        page.mouse.move(box["x"] + x * box["width"], box["y"] + y * box["height"], steps=6)
    page.mouse.up()


DONE = "document.querySelectorAll('#history li').length === {n} && !document.querySelector('#history li.busy')"

LEFT = "#history li[data-left]"  # History's mark on an erase that the page's check holds back (logic.eraseCheck), or that asks for its object's name
ASKED = "document.querySelector('#ask').open"  # the page's question dialog: while it is open, the page behind it takes no click
ENDED = ("Export: done", "Download: ")  # the status line once the export is written, then once its zip downloads
NAME_ASKED = "took the stroke for another object"  # the page's line when an erase with no words asks for its object's name (logic.asksName)


class NameAsked(Exception):
    """The page asked for an erase's object by name, and ran nothing: the case ends there (gpu_matrix.json, « expect »)."""


def flow(page, url, open_plate, shots, wait_s=120):
    """The flow both runs share: the page must already show 'Ready'."""
    status = lambda: page.inner_text("#status")  # noqa: E731
    open_plate()
    page.wait_for_function("document.querySelector('#spec').textContent && document.querySelector('#opening').hidden", timeout=wait_s * 1000)
    print("opened:", status(), "|", page.inner_text("#spec"))
    page.keyboard.press("Space"); page.wait_for_timeout(600); page.keyboard.press("Space")  # play, then pause
    playing_frame = page.inner_text("#frame-now")
    page.keyboard.press("Home")
    box = page.locator("#view").bounding_box()
    for i, (tool, words, pts) in enumerate((("paint", "a fire", [(0.3, 0.6), (0.4, 0.5), (0.45, 0.65)]),
                                           ("erase", "", [(0.7, 0.3), (0.75, 0.4)]),
                                           ("light", "warm sunset", [(0.1, 0.1), (0.2, 0.15)]))):
        pick(page, tool)
        page.fill("#prompt", words)
        page.locator("#prompt").blur()
        stroke(page, box, pts)
        page.keyboard.press("Enter")  # Generate: the edit, then its shot
        settled = f"({DONE.format(n=i + 1)}) && !document.querySelector('{LEFT}')"
        page.wait_for_function(f"{ASKED} || ({settled})", timeout=wait_s * 1000)
        if page.evaluate(ASKED):  # the check holds this erase back: a stand-in edit keeps the object's edges. « Render anyway » keeps the first frame, and its shot renders
            print(f"edit {tool}: asked |", page.inner_text("#ask-text"))
            page.click("#ask-yes")
            page.wait_for_function(f"!{ASKED} && ({settled})", timeout=wait_s * 1000)
        page.screenshot(path=f"{shots}/2_{tool}_done.png")
        print(f"edit {tool}: done |", status())
    page.locator("#history li").nth(1).locator(".eye").click()  # bypass the erase, then bring it back
    page.wait_for_function("document.querySelectorAll('#history li.off').length === 1 && !document.querySelector('#history li.busy')",
                           timeout=wait_s * 1000)
    page.locator("#history li").nth(1).locator(".eye").click()
    page.wait_for_function("!document.querySelector('#history li.off') && !document.querySelector('#history li.busy')", timeout=wait_s * 1000)
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=wait_s * 3000)
    page.keyboard.press("F6")  # wipe on, at frame 10
    page.keyboard.press("End")
    page.screenshot(path=f"{shots}/3_full_size_wipe.png")
    with page.expect_download(timeout=wait_s * 3000) as dl:  # Export: only now is the result written in the plate's format
        page.click("#export-btn")
        page.check("#x-review")
        page.click("#x-go")
    final = status()
    print("final:", final, "| frame while playing:", playing_frame, "| steps:", page.inner_text("#stages").replace("\n", " "))
    path = f"{shots}/download.zip"
    dl.value.save_as(path)
    names = zipfile.ZipFile(path).namelist()
    print("zip:", len(names), "files;", sorted({n.split("/")[0] for n in names}))
    return final, names


def rows(i, fluid):
    """History's rows once edit `i` (from 0) is made: a fluid shot has a row of its own."""
    return i + 1 + bool(fluid)


def stage(note):
    """The stage that a note of the render names: « preview about 14 s left » and « preview almost ready » are « preview »."""
    return note.split(" about ")[0].split(" almost ")[0]


def address(url, memory="", seed=None):
    """The page's address for a run on real models. ?index=0: the page leaves its job index alone, so every job runs, and
    each time and each peak of memory is a measured one, on a machine that ran the same strokes before too. ?seed=: every
    new edit and every new fluid shot starts from this seed, so the next run starts from the same."""
    options = ["blank=0", "index=0"] + ([f"memory={memory}"] if memory else []) + ([f"seed={seed}"] if seed is not None else [])
    return f"{url}/extensions/ainvfx-paintaplate/paintaplate.html?" + "&".join(options)


def answers(url):
    """Whether the ComfyUI at `url` still answers. On 11 Nov a memory cap stopped ComfyUI during a render, twice: the page
    waited, this script with it, and no report was written."""
    try:
        urllib.request.urlopen(url + "/system_stats", timeout=5).close()
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy", required=True); ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--port", type=int, default=8190)
    ap.add_argument("--url", default="", help="a running ComfyUI with the real workflows and models (no stand-ins)")
    ap.add_argument("--path", default="", help="plate path in that ComfyUI's input folder, typed into the open dialog")

    ap.add_argument("--strokes", default="", help='JSON list of [tool, words, [[x, y], ...], brush size, {"whole": false, "color": "#d32f2f"}]')
    ap.add_argument("--fluid", default="", help='with --url: a fluid shot from a blank plate first, as fluid_shot() describes; '
                    '--strokes then edit it as the plate')
    ap.add_argument("--timeout", type=int, default=150)
    ap.add_argument("--out", default=SHOTS, help="folder for screenshots and timings")
    ap.add_argument("--think", type=float, default=0, help="seconds between opening the plate and the first stroke")
    ap.add_argument("--graph", action="store_true", help="after the export, also save the scene's ComfyUI graph")
    ap.add_argument("--memory", default="", help="with --url: the page's memory profile, small, medium or large (by default the card decides)")
    ap.add_argument("--hdr", action="store_true", help="with --url: turn SDR to HDR on in Deliver before painting, so the render makes "
                    "its full-size shot again in scene-linear values and HDR Match fits it to the plate")
    ap.add_argument("--seed", type=int, default=None, help="with --url: the seed of every new edit and fluid shot, the page's ?seed= (by default the page draws each one)")
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
            browser = p.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1280, "height": 800}, accept_downloads=True)
            page.on("console", lambda m: (m.type == "error" and errors.append(m.text), print("   [console]", m.type, m.text[:200])))
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{url}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
            page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=30000)
            page.screenshot(path=f"{SHOTS}/1_empty.png")

            def open_plate():  # Upload: the EXR frames go to the input folder; the colour space is read from the file
                page.click("#open-btn")
                page.click("#open [data-tab=upload]")
                page.set_input_files("#files", exr)
                page.click("#open-go")
            try:
                final, names = flow(page, url, open_plate, SHOTS)
            except Exception:
                print("status:", page.inner_text("#status"))
                page.screenshot(path=f"{SHOTS}/fail.png")
                raise
            ok = final.startswith(ENDED)
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
    passed = ok and exports and mattes and "review.mp4" in names and not errors
    print("UI FLOW PASSED" if passed else "UI FLOW FAILED")
    return 0 if passed else 1


def fluid_shot(page, spec, shots, mark, wait_s=900):
    """A fluid shot from a blank plate: the keyframes painted stroke by stroke, then one ainvfx-fluid pass.

    `spec`: {"size": [w, h], "fps": 24, "frames": 121, "words": "...", "keys": [[frame, colour, [[x, y], ...], brush], ...]}.
    A key's frame is 0, -1 for the last frame, or 8k + 1 between; its colour is one of the page's swatches. Strokes on
    one frame build one keyframe, so flat zones for sky and ground can go under the fluid's blob, as the model card says.
    """
    page.click("#open-btn")
    page.click("#open [data-tab=blank]")
    w, h = spec.get("size", [960, 512])
    page.fill("#b-width", str(w)); page.fill("#b-height", str(h))
    page.select_option("#b-fps", str(spec.get("fps", 24))); page.fill("#b-frames", str(spec.get("frames", 121)))
    page.dispatch_event("#b-frames", "input")
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=120000)
    mark("blank plate open: " + page.inner_text("#spec"))
    page.fill("#prompt", spec.get("words", "")); page.evaluate("document.activeElement.blur()")
    box = page.locator("#view").bounding_box()

    def seek(frame):
        page.evaluate("document.activeElement.blur()")
        page.keyboard.press("End" if frame < 0 else "Home")
        for _ in range(max(frame, 0)):
            page.keyboard.press("ArrowRight")

    for frame, color, pts, size in spec["keys"]:
        seek(frame)
        page.click(f".swatches .sw[data-color='{color}']")
        page.eval_on_selector("#size", "(el, v) => { el.value = v; el.dispatchEvent(new Event('input')); }", size)
        stroke(page, box, pts)
    frames = sorted({k[0] for k in spec["keys"]}, key=lambda f: (f < 0, f))
    for f in frames:
        seek(f); page.locator("#view").screenshot(path=f"{shots}/0_key_{'last' if f < 0 else f}.png")
    mark(f"fluid: {len(frames)} keyframes, {len(spec['keys'])} strokes")
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    page.wait_for_function("/generating/.test(document.querySelector('#fluid-state').textContent)", timeout=60000)
    mark("fluid: generating")
    page.wait_for_function("""(() => { const r = document.querySelector('#history li[data-id="fluid"]');
      return !!r && !r.classList.contains('busy') && document.querySelector('#fluid').hidden && document.querySelector('#opening').hidden; })()""",
                           timeout=wait_s * 1000)  # made: the first edit, and the plate under the next ones; a small card needs longer
    mark("fluid: shot ready | " + page.inner_text("#status"))


def remote(a):
    """The real page, workflows and models on a remote ComfyUI: a timed mark for every stage."""
    shots = a.out
    nodes, began = [], time.time()  # when ComfyUI started each node: nodes.json, for the report's node times
    shutil.rmtree(shots, ignore_errors=True); os.makedirs(shots)
    fluid = json.loads(a.fluid) if a.fluid else None
    default = [] if fluid else [["paint", "a small campfire", [[0.45, 0.8], [0.5, 0.75], [0.55, 0.8]]]]
    strokes = json.loads(a.strokes) if a.strokes else default
    marks, errors, t0 = [], [], time.time()
    mark = lambda what: (marks.append((round(time.time() - t0, 1), what)), print(f"{marks[-1][0]:7.1f} s  {what}"))  # noqa: E731
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=a.channel or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page.on("websocket", executing(nodes, began))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        status = lambda: page.inner_text("#status")  # noqa: E731
        try:
            page.goto(address(a.url, a.memory, a.seed))
            page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
            mark("page ready: " + status())
            if fluid:  # a fluid shot first: once made, it is the plate the strokes are painted on
                fluid_shot(page, fluid, shots, mark, wait_s=max(900, 4 * a.timeout))
            else:
                page.click("#open-btn"); page.click("#open [data-tab=files]"); page.fill("#path", a.path); page.click("#open-go")
                page.wait_for_function("document.querySelector('#spec').textContent && document.querySelector('#opening').hidden", timeout=300000)
            if strokes:
                mark("plate open: " + page.inner_text("#spec")); page.screenshot(path=f"{shots}/1_open.png")
                if a.hdr:
                    mark(deliver_hdr(page))
                box = page.locator("#view").bounding_box()
                page.wait_for_timeout(a.think * 1000)  # a person looks at the frame before painting
                for i, (tool, words, pts, *size) in enumerate(strokes):
                    pick(page, tool); page.fill("#prompt", words); page.locator("#prompt").blur()
                    if size:  # brush size in frame pixels, set on the slider
                        page.eval_on_selector("#size", "(el, v) => { el.value = v; el.dispatchEvent(new Event('input')); }", size[0])
                    opts = size[1] if len(size) > 1 else {}  # options after the brush size
                    if "whole" in opts:  # {"whole": false} paints an erase as is
                        page.set_checked("#whole", opts["whole"])
                    if "color" in opts:  # {"color": "#d32f2f"}: a swatch for the paint or the light
                        page.click(f".swatches .sw[data-color='{opts['color']}']")
                    stroke(page, box, pts); mark(f"{tool} stroke")
                    page.keyboard.press("Enter")  # Generate
                    page.wait_for_function("document.querySelector('#history li.busy .state')", timeout=60000)
                    # a small card loads its models in turn. A row marked left ends the wait at once: behind the page's dialog
                    # (« Render anyway » or « Cancel ») the row can stay busy, which held the wait to its timeout
                    page.wait_for_function(f"({DONE.format(n=rows(i, fluid))}) || !!document.querySelector('{LEFT}')", timeout=max(300, 2 * a.timeout) * 1000)
                    if page.query_selector(LEFT):  # no shot will render: without this the run waited 8 times --timeout for one
                        page.screenshot(path=f"{shots}/2_{tool}_done.png")
                        said = [status(), *page.eval_on_selector_all("#log li", "els => els.slice(-5).map(e => e.textContent)")]
                        if any(NAME_ASKED in line for line in said):
                            raise NameAsked(next(line for line in said if NAME_ASKED in line))
                        raise RuntimeError("the erase left its object")
                    mark(f"{tool} edit on the first frame | {status()}"); page.screenshot(path=f"{shots}/2_{tool}_done.png")
                seen, silent, asked = set(), 0, time.time()
                deadline = time.time() + a.timeout * 8
                while time.time() < deadline:
                    note = page.inner_text("#render-left")
                    tag = stage(note) if note else status()[:40]
                    if tag not in seen:
                        seen.add(tag); mark("stage: " + (note or status()))
                    if note == "full size ready" or "Error" in status() or status().startswith("Missing"):
                        break
                    if time.time() - asked >= 10:  # a ComfyUI stopped for its memory leaves the page waiting: the case ends here, with what it has
                        asked, silent = time.time(), 0 if answers(a.url) else silent + 1
                        if silent >= 3:
                            mark(f"FAILED: ComfyUI stopped answering in « {note or status()[:60]} ».")
                            break
                    time.sleep(1)
                mark("final: " + status())
                page.keyboard.press("F6"); page.keyboard.press("End"); time.sleep(1); page.screenshot(path=f"{shots}/3_wipe.png")
                page.keyboard.press("F6"); page.keyboard.press("Home"); page.keyboard.press("Space"); time.sleep(2)
                page.keyboard.press("Space"); page.screenshot(path=f"{shots}/4_played.png")
                if page.inner_text("#render-left") == "full size ready":  # Export writes the result, then the zip downloads
                    with page.expect_download(timeout=600000) as dl:
                        page.click("#export-btn")
                        page.click("#x-go")
                    dl.value.save_as(f"{shots}/export.zip")
                    mark(f"downloaded {len(zipfile.ZipFile(f'{shots}/export.zip').namelist())} files")
                    if a.graph:  # the scene as one ComfyUI workflow, from the Export dialog. A case does not depend on it
                        try:
                            page.click("#export-btn")
                            with page.expect_download(timeout=120000) as dl:
                                page.click("#x-graph")
                            dl.value.save_as(f"{shots}/scene.comfyui.json")
                            mark(f"ComfyUI graph saved: {len(json.load(open(f'{shots}/scene.comfyui.json'))['nodes'])} nodes and notes")
                        except Exception as exc:
                            mark(f"ComfyUI graph not saved: {type(exc).__name__}: {str(exc).splitlines()[0][:120]} | status: {status()}")
        except NameAsked as exc:
            mark(f"name asked: {exc}")
        except Exception as exc:
            mark(f"FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:160]} | status: {status()}")
            page.screenshot(path=f"{shots}/fail.png")
        page_log = page.eval_on_selector_all("#log li", "els => els.map(e => e.textContent)")  # what ran, with which values
        browser.close()
    open(f"{shots}/page_log.txt", "w").write("\n".join(page_log) + "\n")
    json.dump({"marks": marks, "errors": errors}, open(f"{shots}/timings.json", "w"), indent=1)
    json.dump(nodes, open(f"{shots}/nodes.json", "w"))
    print("console errors:", errors[:5])
    return 0


if __name__ == "__main__":
    sys.exit(main())
