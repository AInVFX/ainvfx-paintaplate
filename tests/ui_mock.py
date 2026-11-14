"""The page's behaviour in headless Chromium against tests/mock_comfy.py: no ComfyUI, no GPU.

    python tests/ui_mock.py                     every flow
    python tests/ui_mock.py --list              the flows' names
    python tests/ui_mock.py --only keys,scene   the flows named
    python tests/ui_mock.py --jobs 4            four flows side by side (default: one per CPU)
    python tests/ui_mock.py --speed 1           the mock's jobs at their full simulated time (default: 8 times shorter)
    python tests/ui_mock.py --shard 2/4         the second of four parts of the flows, for machines side by side (the CI)

A flow is one subject of the page: the Open dialog, a first edit and its render, a fluid shot, the keys. Each flow runs in
its own process, against its own mock ComfyUI (its own port and folders) and its own browser. So a flow starts from its own
page load and leaves nothing another flow needs, a failure ends its own flow only, and flows run in any order, side by
side. The run prints each flow's checks, then a table (flow, checks, time, first failure), and exits with 1 when a flow
failed. Screenshots and each mock's log go to /tmp/paintaplate_ui_mock. tests/test_ui_mock.py runs it.

The flows of this file are in FLOWS. Each module of tests/flows adds one, named after its file (tests/flows/README.md).
"""
import argparse, json, os, queue, re, shutil, signal, subprocess, sys, threading, time, traceback, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHOTS = "/tmp/paintaplate_ui_mock"
PAGE = "http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html{query}"
VIEWPORT = {"width": 1400, "height": 900}
DONE = "document.querySelectorAll('#history li').length === {n} && !document.querySelector('#history li.busy')"
REVIEWED = "Composite, full size done in"  # a render's full-size composite in the log: "Render v2: Composite, full size done in 3.1 s."
CHECKS = {"passed": 0, "failed": None}  # this process's checks: how many passed, and the sentence of the one that failed


def check(ok, what):
    """One check: its sentence says what it proves. A failed check ends its flow."""
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        CHECKS["failed"] = what
        raise AssertionError(what)
    CHECKS["passed"] += 1


# ---------- What the flows share: a page, a plate, a stroke, the log ----------

def load(browser, port, query="?blank=0", errors=None, **context):
    """A new page with the app loaded. `errors` collects console errors, page errors and failed requests, from the load on."""
    page = browser.new_page(viewport=VIEWPORT, **context)
    if errors is not None:
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("response", lambda r: errors.append(f"{r.status}: {r.url}") if r.status >= 400 else None)
    page.goto(PAGE.format(port=port, query=query))
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    return page


def no_errors(errors, where):
    errors = [e for e in errors if "favicon" not in e]
    check(not errors, f"no console errors {where}: {errors}")



def mock_route(port, path, body=None):
    """A route of the mock ComfyUI: a GET, or a POST of `body`. Returns its answer, read as JSON."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as r:
        return json.load(r)


def open_path(page, path):
    """Open plate, ComfyUI files: a path typed into the dialog, then Open."""
    page.click("#open-btn"); page.click("#open [data-tab=files]"); page.fill("#path", path); page.click("#open-go")


def open_plate(page, path="plates/desk.mp4"):
    """A plate opened from ComfyUI's files, its spec read and the page ready for an edit."""
    open_path(page, path)
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps')", timeout=60000)
    page.wait_for_function("/Describe the edit|Plate ready/.test(document.querySelector('#status').textContent)", timeout=60000)


def view_box(page):
    return page.eval_on_selector("#view", "e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }")


def stroke(page, pts):
    """A brush stroke through points given from 0 to 1 across the frame."""
    box = view_box(page)
    page.mouse.move(box["x"] + pts[0][0] * box["w"], box["y"] + pts[0][1] * box["h"])
    page.mouse.down()
    for x, y in pts[1:]:
        page.mouse.move(box["x"] + x * box["w"], box["y"] + y * box["h"], steps=5)
    page.mouse.up()


def paint_once(page, words, pts):
    """The words typed in the prompt, then one stroke."""
    page.fill("#prompt", words); page.evaluate("document.activeElement.blur()")
    stroke(page, pts)


def row_titles(page):  # History, newest first: "2. Clean", "1. Paint"
    return page.eval_on_selector_all("#history li .title", "els => els.map(e => e.textContent)")


def row_words(page):
    return page.eval_on_selector_all("#history li small", "els => els.map(e => e.textContent)")


def log_lines(page):
    return page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")


def klein_passes(page):  # Klein passes run so far: a result used again adds none
    return sum("Klein quick pass" in line for line in log_lines(page))


# ---------- Waiting: on what the page shows, never on the clock ----------

QUIET_MS = 600  # the one wait on the clock, for a check that nothing starts: longer than the page's own delays after an input (PREFETCH_MS 500, IDLE_MS 300 in app.mjs)
SETTLED = """() => { const calm = document.querySelector('#stop').hidden && !document.querySelector('#history li.busy');
  if (!calm) return void (window.__calm = 0);
  return performance.now() - (window.__calm ||= performance.now()) >= 700; }"""


def until(page, js, timeout=10000, arg=None):
    """Whether the page reaches a state in time (page.wait_for_function), for a check that then says what was missing."""
    try:
        page.wait_for_function(js, arg=arg, timeout=timeout)
        return True
    except Exception as exc:
        if type(exc).__name__ != "TimeoutError":
            raise
        return False


def poll(page, test, seconds=5):
    """Whether `test`, a Python function, comes true within `seconds`. The page goes on while it waits."""
    end = time.time() + seconds
    while not test():
        if time.time() > end:
            return False
        page.wait_for_timeout(25)
    return True


def settled(page, timeout=180000):
    """No edit and no render step left: nothing generates for 700 ms running. A render starts 300 ms after a change (IDLE_MS
    in app.mjs), so a shorter calm can be the gap before the next step."""
    page.evaluate("window.__calm = 0")
    page.wait_for_function(SETTLED, timeout=timeout)


def rested(page, seen):
    """The strokes have rested since the log's line `seen`: for an erase stroke, SAM 3.1 has found the object under it and
    Klein's prompt writer has written its caption. The page asks both as the stroke ends, before Generate."""
    lines = "[...document.querySelectorAll('#log li span')].slice(%d).map((e) => e.textContent)" % seen
    wait_log(page, f"['under the stroke', 'caption from the prompt writer'].every((text) => {lines}.some((line) => line.includes(text)))",
             30000, "answer from SAM and the prompt writer for the stroke")



WATCH = """() => { window.__lines = []; if (window.__watch) window.__watch.disconnect();
  window.__watch = new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) =>
    (n.querySelectorAll ? [...n.querySelectorAll('span')] : [n]).forEach((s) => window.__lines.push(s.textContent)))));
  window.__watch.observe(document.querySelector('#log'), { childList: true, subtree: true }); }"""  # lines added from now on


def added(page, steps):  # how many jobs of each step were taken from the job index, and how many were posted, since WATCH
    lines = page.evaluate("window.__lines")  # a posted job's lines start with its step and its id: "ingest ef88a8f3: done in 2.0 s (10 nodes)"
    return {**{f"{s}: made before": sum(line.startswith(f"{s}: made before") for line in lines) for s in steps},
            **{f"{s}: posted": len({line.split(":")[0] for line in lines if line.startswith(f"{s} ")}) for s in steps}}


def added_line(text):  # a JS test: a line added to the log since WATCH holds `text` (the log keeps its last 400 lines only)
    return "window.__lines.some((t) => t.includes(%s))" % json.dumps(text)


def wait_log(page, js, timeout, what):
    """page.wait_for_function; on a timeout, the page's last log lines, its render steps and its status, so a CI log says why."""
    try:
        page.wait_for_function(js, timeout=timeout)
    except Exception:
        print(f"  ... no {what}; the page's last log lines:\n    " + "\n    ".join(log_lines(page)[-30:]), flush=True)
        print("  stages:", page.text_content("#stages"), "| status:", page.text_content("#status"), flush=True)
        raise


def page_state(page):  # what a failed check prints: the status line, the plate's spec and the log's last lines
    lines = "\n    ".join(log_lines(page)[-15:])
    return f"\n  status: {page.text_content('#status')!r}\n  spec: {page.text_content('#spec')!r}\n  log's last lines:\n    {lines}"


def save_scene(page):
    """Save scene keeps it on this ComfyUI: the newest scene, read back through the scenes route."""
    saved = "[...document.querySelectorAll('#log li span')].filter((e) => /saved on this ComfyUI/.test(e.textContent)).length"
    before = page.evaluate(saved)
    page.click("#save-btn")
    page.wait_for_function(f"{saved} > {before}", timeout=20000)  # the log keeps the fact: a later sentence can replace it in the status line
    base = page.url.split("/extensions/")[0]
    name = json.loads(urllib.request.urlopen(f"{base}/paintaplate/scenes").read())[0]["name"]
    return name, json.loads(urllib.request.urlopen(f"{base}/paintaplate/scenes/{name}").read())


def open_scene(page, name):
    """Open plate, Scenes: the scene by its name, then Open."""
    page.click("#open-btn"); page.click("#open [data-tab=scenes]")
    page.wait_for_selector("#scenes .scene", timeout=10000)
    page.evaluate("(n) => [...document.querySelectorAll('#scenes .scene')].find((b) => b.querySelector('.name').textContent === n).click()", name)
    page.click("#open-go")


def menu(page, *labels):
    """Right-click the frame, then go through RV's submenus to the item, as a person would with a mouse."""
    page.click("#view", button="right")
    for label in labels[:-1]:
        page.locator("#ctx li.group > span:first-child", has_text=re.compile(f"^{re.escape(label)}$")).first.hover()
    page.get_by_role("menuitemcheckbox", name=labels[-1], exact=True).click()


def drag(page, selector, dx, dy):
    box = page.locator(selector).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + dx, y + dy, steps=5); page.mouse.up()


# ---------- The flows: each opens its own page and closes it ----------

def start_flow(browser, port):
    """With no plate open, the page opens a blank plate at start, at the Blank tab's settings, in 16-bit when SDR to HDR can
    run, its keyframes ready to paint (?blank=0 starts empty, as every other flow does)."""
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    spec = page.text_content("#spec")
    check("960 × 512, 25 fps, 121 frames" in spec and page.input_value("#b-depth") == "16" and not page.is_hidden("#fluid"),
          f"a blank plate opens at start, 16-bit, its keyframes ready to paint: {spec}")
    page.close()


def open_flow(browser, port):
    """The Open dialog: the Input root lists the plates of the folders below it, the plate browser opens input/plates with
    its breadcrumbs, one click reads the plate and its colour space, each tab shows one source; then the plate opens and
    the preview menu comes from it."""
    items = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/paintaplate/browse?path=plates").read())["items"]
    check([i["path"] for i in items] == ["plates/desk.mp4"], "the browse route lists the mock's plate")
    errors = []
    page = load(browser, port, errors=errors)
    version = page.text_content("#version") or ""
    first = page.eval_on_selector_all("#log li span", "els => els.slice(0, 3).map(e => e.textContent)")
    check(version.count(".") == 2 and any(t.startswith(f"AInVFX Paint a plate {version} (build ") for t in first),
          f"the top bar shows the pack's version, and the log names it first with the server's build: {version} {first}")

    page.click("#open-btn")
    page.wait_for_selector("#browse .item.video:has-text('desk.mp4')", timeout=10000)
    below = page.text_content("#browse .item.video:has-text('desk.mp4') small") or ""
    check(below.startswith("plates"), f"the Input root lists the plates of the folders below it, each with its folder: {below}")
    page.click("#browse .item.folder:has-text('plates')")
    # the root lists the plates found below it too, so a video shows at once: wait for the folder itself, by its breadcrumbs
    page.wait_for_function("[...document.querySelectorAll('#crumbs button')].map((b) => b.textContent).join('/') === 'Input/plates'", timeout=10000)
    page.wait_for_selector("#browse .item.video", timeout=10000)
    names = page.eval_on_selector_all("#browse .item .name", "els => els.map(e => e.textContent)")
    trail = page.eval_on_selector_all("#crumbs button", "els => els.map(e => e.textContent)")
    check("desk.mp4" in names and trail == ["Input", "plates"], f"the plate browser lists input/plates, with breadcrumbs: {names} {trail}")
    page.click("#browse .item:has-text('desk.mp4')")
    page.wait_for_function("document.querySelector('#browse-info').textContent.includes('Colour space')", timeout=10000)
    info = page.text_content("#browse-info")
    check("1280 × 704" in info and "49 frames" in info and "sRGB Encoded Rec.709 (sRGB)" in info and not page.is_disabled("#open-go"),
          f"one click reads the plate and its colour space in the OCIO config: {info}")
    shown = {}
    for t in ("upload", "scenes", "blank", "files"):
        page.click(f"#open [data-tab={t}]")
        shown[t] = page.evaluate("[...document.querySelectorAll('#open .tab')].filter((s) => !s.hidden).map((s) => s.dataset.tab).join()")
    check(all(v == k for k, v in shown.items()), f"one tab per source: ComfyUI files, Upload, Scenes, Blank plate: {shown}")
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps')", timeout=60000)
    page.wait_for_function("/Describe the edit|Plate ready/.test(document.querySelector('#status').textContent)", timeout=60000)
    menu = page.eval_on_selector_all("#preview-size option", "els => els.map(e => e.textContent)")
    check(any("Fast · 640 × 352 (1/2)" in m for m in menu) and menu[0].startswith("Full"), f"the preview menu comes from the plate: {menu}")
    page.screenshot(path=os.path.join(SHOTS, "1_open.png"))
    no_errors(errors, "in the Open dialog")
    page.close()


def colour_flow(browser, port):
    """Colour: an EXR keeps its range through the frame route and the viewer's OCIO program, and a channel comes from the
    values the view shows. Then on a plate, as in RV: a channel in grey, an exposure drag that paints nothing, the
    right-click menu and its Reset all colour, and the colour picker."""
    errors = []
    page = load(browser, port, errors=errors)
    hdr = page.evaluate("""async () => { // an EXR through the frame route and the viewer's shader, as the colour tools see it
      const { Display, DISPLAY } = await import(new URL("display.mjs", location.href).href); // the colour model lives in display.mjs since 1.5.0
      const r = await fetch("/paintaplate/frames?path=paintaplate/hdr_test&first=0&count=1&side=64");
      const [width, height] = r.headers.get("X-Frame-Size").split("x").map(Number), out = document.createElement("canvas");
      const frame = { width, height, data: new Uint16Array(await r.arrayBuffer()) }, space = "Linear Rec.709 (sRGB)";
      let ready;
      const loaded = new Promise((ok) => (ready = ok)), look = new Display({ onready: () => ready() });
      look.setView({ config: "", display: "sRGB - Display", view: "Un-tone-mapped", look: "" });
      look.image(frame, DISPLAY, space); // the OCIO program loads once, from the server's GLSL
      await loaded;
      [out.width, out.height] = [width, height];
      const x = out.getContext("2d", { willReadFrequently: true }), read = (stops) => {
        x.drawImage(look.image(frame, { ...DISPLAY, exposure: stops }, space), 0, 0);
        return [x.getImageData(8, height >> 1, 1, 1).data[0], x.getImageData(width - 9, height >> 1, 1, 1).data[0]];
      };
      const stops0 = read(0), down2 = read(-2);
      // a saturated 8-bit red through the sRGB program: the channel comes from the values the view shows, as in RV
      const red = Object.assign(document.createElement("canvas"), { width: 8, height: 8 }), paint = red.getContext("2d");
      paint.fillStyle = "rgb(179, 30, 27)";
      paint.fillRect(0, 0, 8, 8);
      const srgb = "sRGB Encoded Rec.709 (sRGB)", again = new Promise((ok) => (ready = ok));
      look.image(red, { ...DISPLAY, channel: "r" }, srgb); // a second program, for this colour space
      await again;
      const grey = (channel) => {
        x.clearRect(0, 0, width, height);
        x.drawImage(look.image(red, { ...DISPLAY, channel }, srgb), 0, 0);
        return [...x.getImageData(4, 4, 1, 1).data.slice(0, 3)];
      };
      return { size: [width, height], stops0, down2, red: grey("r"), luma: grey("l") };
    }""")
    check(hdr["stops0"][0] >= 254 and hdr["down2"][0] >= 253 and abs(hdr["stops0"][1] - 188) <= 2 and abs(hdr["down2"][1] - 99) <= 2,
          f"an EXR keeps its range through the frame route and the viewer's OCIO program: 4.0 stays white two stops down, 0.5 goes from 188 to 99: {hdr}")
    check(all(abs(v - 179) <= 2 for v in hdr["red"]) and all(abs(v - 61) <= 2 for v in hdr["luma"]),
          f"a channel comes from the values the view shows, as RV's OCIODisplay floods it: [179, 30, 27] shows red 179 and luminance 61: {hdr['red']} {hdr['luma']}")
    open_plate(page)
    box = view_box(page)
    page.evaluate("document.activeElement.blur()")
    cx, cy = box["x"] + box["w"] * 0.5, box["y"] + box["h"] * 0.5
    page.mouse.move(cx, cy)
    # the viewer's colour lives in the canvas pixels now (a WebGL2 shader), so the checks read them
    pixel = lambda fx=0.5, fy=0.5: page.evaluate("""([fx, fy]) => { const c = document.querySelector('#view'), s = [0, 0, 0];
      const d = c.getContext('2d').getImageData(Math.round(c.width * fx) - 2, Math.round(c.height * fy) - 2, 5, 5).data;
      for (let i = 0; i < d.length; i += 4) for (let k = 0; k < 3; k++) s[k] += d[i + k] / 25; return s; }""", [fx, fy])
    grid = [(x / 10, y / 10) for x in range(1, 10) for y in range(1, 10)]  # a point lit enough to see one more stop
    spot = max(grid, key=lambda p: (lambda v: v[0] if 40 < v[0] < 180 else -abs(v[0] - 110))(pixel(*p)))
    before = pixel(*spot)
    page.keyboard.press("Shift+R")
    red = pixel(*spot)
    check(page.text_content("#display-state") == "Red" and max(red) - min(red) < 3 and abs(red[0] - before[0]) < 4,
          f"Shift+R shows the red channel in grey, as RV's r: {[round(v) for v in before]} then {[round(v) for v in red]}")
    page.keyboard.press("Shift+E")
    page.mouse.down(); page.mouse.move(cx + 100, cy, steps=5); page.mouse.up()
    label, up = page.text_content("#display-state"), pixel(*spot)
    check(label.startswith("E +1.0") and page.is_disabled("#undo-btn") and (up[0] > red[0] + 8 or red[0] > 240),
          f"Shift+E then a 100 px drag adds one stop to the pixels and paints nothing: {label}, red {red[0]:.0f} to {up[0]:.0f}")
    page.mouse.click(cx, cy, button="right")
    groups = page.eval_on_selector_all("#ctx > li > span:first-child", "els => els.map(e => e.textContent)")
    check(groups == ["File", "Edit", "Tools", "Control", "Colour", "OCIO", "View", "Help"], f"right-click opens the menu: {groups}")
    page.hover(f"#ctx > li:nth-child({groups.index('Colour') + 1})")  # by place: Tools holds « Pick a colour » too
    page.screenshot(path=os.path.join(SHOTS, "3_menu.png"))
    page.click("#ctx .sub button:has-text('Reset all colour')")
    back = pixel(*spot)
    check(page.is_hidden("#display-state") and page.is_hidden("#ctx") and all(abs(p - q) < 3 for p, q in zip(back, before)),
          "Reset colour in the menu brings the pixels back and closes the menu")
    # The colour picker: I arms the in-frame picker, and a click gives the brush the frame's own colour there
    color = page.input_value("#color")
    page.keyboard.press("i")
    check(page.evaluate("document.querySelector('#view').classList.contains('picking')"), "I arms the in-frame picker")
    want = pixel(0.9, 0.1)
    page.mouse.click(box["x"] + box["w"] * 0.9, box["y"] + box["h"] * 0.1)
    got = page.input_value("#color")
    rgb = [int(got[i:i + 2], 16) for i in (1, 3, 5)]
    check(got != color and all(abs(p - q) <= 6 for p, q in zip(rgb, want)) and not page.evaluate("document.querySelector('#view').classList.contains('picking')"),
          f"a click on the frame picks the frame's colour there: {got} against the frame's {[round(v) for v in want]}")
    page.fill("#color", color)
    no_errors(errors, "with the viewer's colour")
    page.close()


def generate_flow(browser, port):
    """A first edit and its render: the strokes wait for Generate, Enter makes the edit, then the full-size composite and
    nothing for compositing software; Export writes the result and its matte, and the scene as one ComfyUI graph; paused,
    the viewer shows the shot; Enter again with nothing changed runs nothing; the log says what happens under the hood."""
    errors = []
    page = load(browser, port, errors=errors)
    open_plate(page)
    page.fill("#prompt", "a red fire")
    stroke(page, [(0.3, 0.5), (0.4, 0.52), (0.5, 0.5)])
    stroke(page, [(0.3, 0.6), (0.5, 0.62)])
    check(not page.is_disabled("#undo-btn"), "undo is live after a stroke")
    page.wait_for_timeout(QUIET_MS)
    check(row_titles(page) == [] and not page.is_disabled("#generate"), f"the strokes wait for Generate: nothing starts by itself {row_titles(page)}")
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check(row_titles(page) == ["1. Paint"] and row_words(page) == ["a red fire"], f"Enter generates edit 1 with its words: {row_titles(page)} {row_words(page)}")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=120000)
    lines = log_lines(page)
    full = [i for i, line in enumerate(lines) if "plays the full-size shot" in line]
    done = [i for i, line in enumerate(lines) if REVIEWED in line]
    check(bool(full and done) and full[-1] < done[-1] and not any(line.startswith("Export v") for line in lines),
          f"Generate makes the full-size composite and nothing for compositing software: the full-size shot plays, then the review: {full} {done}")
    with page.expect_download(timeout=120000) as dl:
        page.click("#export-btn"); page.click("#x-go")
    zipped = zipfile.ZipFile(dl.value.path()).namelist()
    lines = log_lines(page)
    check(any(n.startswith("export/") for n in zipped) and any(n.startswith("matte/") for n in zipped) and any(line.startswith("Export v") for line in lines),
          f"Export writes the result and its matte when pressed, then the zip downloads: {sorted({n.split('/')[0] for n in zipped})}")
    # The ComfyUI graph: the scene in the editor's own format, one group per section in the order they run, each opening with its note
    with page.expect_download(timeout=60000) as dl:
        page.click("#export-btn"); page.click("#x-graph")
    graph = json.load(open(dl.value.path()))
    groups, notes = [g["title"] for g in graph["groups"]], [n for n in graph["nodes"] if n["type"] == "MarkdownNote"]
    overview = notes[0]["widgets_values"][0]
    rects = [(n["pos"][0], n["pos"][1] - 30, n["pos"][0] + n["size"][0], n["pos"][1] + n["size"][1]) for n in graph["nodes"]]  # each with its title bar
    over = sum(min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]) for i, a in enumerate(rects) for b in rects[i + 1:])
    check(graph.get("version") == 0.4 and groups[:3] == ["README", "INPUT", "MODELS"] and any(t.startswith("EDIT 1 · ") for t in groups) and groups[-1] == "OUTPUT"
          and len(notes) == len(groups) and over == 0 and len(graph["links"]) > 100 and f"Paint a plate {page.text_content('#version')}" in overview and "plates/desk.mp4" in overview,
          f"the ComfyUI graph is in the editor's own format: a group per section in the order they run, each with its note, {len(graph['nodes'])} nodes with none over another, {len(graph['links'])} links: {groups}")
    page.evaluate("document.activeElement.blur()")
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    page.wait_for_function("document.querySelector('#view').dataset.picture === 'shot'", timeout=20000)
    page.keyboard.press("Home")
    page.wait_for_function("document.querySelector('#view').dataset.picture === 'shot'", timeout=20000)
    check(page.get_attribute("#view", "data-picture") == "shot", "paused, on frame 3 and on frame 0, the viewer shows the shot, not the plate")
    made, renders = klein_passes(page), page.locator("#log li:has-text('Render v')").count()
    page.keyboard.press("Enter")
    until(page, "document.querySelector('#hud').textContent.includes('Nothing changed')")
    check(klein_passes(page) == made and page.locator("#log li:has-text('Render v')").count() == renders and "Nothing changed" in page.text_content("#hud"),
          "Enter again with nothing changed runs nothing twice: no Klein pass, no render step")
    log = log_lines(page)
    for key in (": done in", "prompt writer", "Klein quick pass"):
        check(any(key in line for line in log), f"the log says what happens under the hood: {key}")
    no_errors(errors, "in a first edit and its render")
    page.close()


def history_flow(browser, port):
    """Edits in History. A whole-object erase as the second edit: SAM runs while the strokes rest. The first edit removed:
    the numbers start again, the erase's matte and clean plate are used again, no render step stops, the render before
    goes on in the background, the preview comes before any full-size step. Undo and redo of the removal. An edit
    selected: its words retyped, another seed. Three undos take the kept results back. The preview size menu."""
    errors = []
    page = load(browser, port, errors=errors)
    open_plate(page)
    paint_once(page, "a red fire", [(0.3, 0.5), (0.4, 0.52), (0.5, 0.5)])
    stroke(page, [(0.3, 0.6), (0.5, 0.62)])
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=120000)
    seen = len(log_lines(page))
    page.click("[data-tool=erase]")
    page.fill("#prompt", "")
    stroke(page, [(0.7, 0.3), (0.75, 0.35)])
    rested(page, seen)  # SAM runs while the strokes rest
    page.click("#generate")
    page.wait_for_function(DONE.format(n=2), timeout=120000)
    check(row_titles(page) == ["2. Clean", "1. Paint"], f"two edits, numbered from the bottom: {row_titles(page)}")
    lines = log_lines(page)[seen:]
    found = next((i for i, line in enumerate(lines) if "under the stroke" in line), len(lines))
    started = next((i for i, line in enumerate(lines) if line.startswith("Edit 2: Clean")), -1)
    asked = sum("asking Klein's prompt writer" in line for line in lines)
    check(found < started and asked == 1, f"a whole-object erase: SAM runs while the strokes rest, the prompt writer once "
          f"(SAM at line {found}, start at line {started}, {asked} request(s))")

    page.wait_for_function("[...document.querySelectorAll('#log li span')].some((e) => e.textContent.includes('Clean plate pass, preview done in'))", timeout=120000)
    seen = len(log_lines(page))
    page.click("#history li:last-child .del")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check(row_titles(page) == ["1. Clean"], f"after a removal the numbers start from 1 again: {row_titles(page)}")
    page.wait_for_function("[...document.querySelectorAll('#log li span')].slice(%d).some((e) => e.textContent.includes('reused from an earlier render'))" % seen,
                           timeout=60000)
    lines = log_lines(page)[seen:]
    check(not any("Track the object (about" in line or "Clean plate pass, preview (about" in line for line in lines),
          "the paint removed, the next render uses the erase's matte and clean plate again: nothing tracks or cleans twice")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=120000)
    lines = log_lines(page)[seen:]
    stopped = [line for line in lines if re.match(r"^(clean|cleanup|shot|matte|comp|review|export) \S+: cancelled", line)]
    check(not stopped, f"a removal stops no render step: the render it leaves keeps what it made {stopped}")
    behind = [line for line in lines if line.endswith(", in the background.")]
    check(bool(behind), f"the render of the edits before the removal goes on in the background: {behind[:2]}")
    steps = [(i, line) for i, line in enumerate(lines) if re.match(r"^Render v\d+: .* \(about \d+ s\)", line)]
    comp = next((i for i, line in steps if "Composite, preview (about" in line and not line.endswith("in the background.")), None)
    full = next((i for i, line in steps if ", full size (about" in line or "Export (about" in line), None)
    check(comp is not None and (full is None or comp < full),
          f"the render queue: the preview of the edits on show runs before any full-size step (composite at {comp}, first full size at {full})")
    check(not page.is_disabled("#undo-btn") and page.is_disabled("#redo-btn"), "undo is live, redo is not")
    page.keyboard.press("Control+z")
    page.wait_for_function(DONE.format(n=2), timeout=120000)
    check(row_titles(page) == ["2. Clean", "1. Paint"] and not page.is_disabled("#redo-btn"), f"undo brings the removed edit back: {row_titles(page)}")
    page.keyboard.press("Control+Shift+z")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check(row_titles(page) == ["1. Clean"], f"redo removes it again: {row_titles(page)}")
    check(page.is_visible("#editing") and page.text_content("#editing") == "Editing 1 · Clean",
          "undo and redo keep the current edit: the next strokes still change it")
    page.keyboard.press("Escape")

    page.click("#history li .what")
    check(page.text_content("#editing") == "Editing 1 · Clean" and page.is_checked("#whole"), "selecting shows the editing tag and the edit's switches")
    page.fill("#prompt", "the lamp")
    page.press("#prompt", "Enter")
    page.wait_for_function("document.querySelector('#history li.busy') !== null", timeout=20000)
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check("the lamp" in page.get_attribute("#history li small", "title"), "retyping the words of a selected edit runs it again with them")
    page.keyboard.press("Escape")
    page.click("#history li .what")
    page.keyboard.press("Control+Enter")
    page.wait_for_function("document.querySelector('#history li.busy') !== null", timeout=20000)
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    log = log_lines(page)
    check(any("another try" in line for line in log), "Ctrl+Enter tries another seed on the selected edit")
    page.keyboard.press("Escape")
    made = klein_passes(page)
    for _ in range(3):
        was = page.text_content("#status")
        page.keyboard.press("Control+z")
        page.wait_for_function("(was) => document.querySelector('#status').textContent !== was", arg=was, timeout=5000)  # « Undone. 2 steps left to undo. »
    page.wait_for_function("!document.querySelector('#history li.busy')", timeout=180000)
    check(row_titles(page) == ["2. Clean", "1. Paint"] and row_words(page) == ["Whole object", "a red fire"],
          f"three undos go back through the seed, the words and the removal: {row_titles(page)} {row_words(page)}")
    check(klein_passes(page) == made, f"undo gets the kept results back: no Klein pass runs again ({klein_passes(page) - made} ran)")
    page.select_option("#preview-size", index=1)
    check("928 x 512" in page.text_content("#status"), "the preview size menu sets the shot size")
    no_errors(errors, "in History")
    page.close()


def one_edit_flow(browser, port):
    """One edit at a time: new words and more strokes change the edit just made; New edit (the N key, the button, the
    right-click menu) or another tool closes it, and the next strokes start a new one."""
    errors = []
    page = load(browser, port, errors=errors)
    open_plate(page)
    box = view_box(page)
    cx, cy = box["x"] + box["w"] * 0.5, box["y"] + box["h"] * 0.5
    page.keyboard.press("p")
    page.fill("#prompt", "a dog"); page.evaluate("document.activeElement.blur()")
    stroke(page, [(0.2, 0.7), (0.25, 0.75)])
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check(row_titles(page)[0] == "1. Paint" and page.is_visible("#editing") and page.text_content("#editing") == "Editing 1 · Paint"
          and page.input_value("#prompt") == "a dog", "the edit just made stays current, its words in the prompt")
    page.locator(".promptbar").screenshot(path=os.path.join(SHOTS, "5_promptbar.png"))
    page.fill("#prompt", "a cat"); page.evaluate("document.activeElement.blur()")
    stroke(page, [(0.26, 0.7), (0.3, 0.74)])
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#history li small')?.textContent === 'a cat' && !document.querySelector('#history li.busy')",
                           timeout=120000)
    check(len(row_titles(page)) == 1 and row_words(page)[0] == "a cat", f"new words and more strokes change the same edit: {row_titles(page)} {row_words(page)}")
    page.keyboard.press("n")
    check(page.is_hidden("#editing") and page.input_value("#prompt") == "" and page.is_disabled("#new-edit"), "N, New edit, closes the current edit")
    page.fill("#prompt", "a bird"); page.evaluate("document.activeElement.blur()")
    stroke(page, [(0.6, 0.7), (0.65, 0.72)])
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=2), timeout=120000)
    check(row_titles(page)[:2] == ["2. Paint", "1. Paint"] and row_words(page)[:2] == ["a bird", "a cat"], f"after New edit the strokes make edit 2: {row_titles(page)} {row_words(page)}")
    page.keyboard.press("l")
    check(page.is_hidden("#editing") and page.input_value("#prompt") == "", "another tool closes the current edit")
    stroke(page, [(0.1, 0.1), (0.2, 0.12)])
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=3), timeout=120000)
    check(row_titles(page)[0] == "3. Light" and row_words(page)[1] == "a bird", f"the light is a new edit: {row_titles(page)} {row_words(page)}")
    page.click("#new-edit")
    check(page.is_hidden("#editing") and page.is_disabled("#new-edit"), "the New edit button closes it too")
    page.click("#history li .what")
    page.mouse.click(cx, cy, button="right")
    page.hover("#ctx > li:has(> span:first-child:text-is('Edit'))")
    page.click("#ctx .sub button:has-text('New edit')")
    check(page.is_hidden("#editing") and len(row_titles(page)) == 3, "New edit in the right-click menu closes the selected edit")
    page.screenshot(path=os.path.join(SHOTS, "2_end.png"))
    no_errors(errors, "with one edit at a time")
    page.close()


def fluid_flow(browser, port):
    """A blank plate: keyframes on the LTX grid, copied, pasted, dragged, deleted and undone; then its shot, the first edit."""
    page = load(browser, port)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8")  # an 8-bit fluid shot: fluid16_flow covers 16-bit, the default once SDR to HDR is installed
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input")
    note = page.text_content("#b-note")
    check(note.startswith("512 × 320, 33 frames at 24 fps"), f"the blank plate form says what it will make: {note}")
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    check(not page.is_hidden("#fluid") and page.is_disabled("[data-tool=erase]") and page.is_disabled("[data-tool=light]"),
          "a blank plate opens as a fluid shot: its panel shows, Clean and Light wait for a plate")

    def keys():
        return page.eval_on_selector_all("#tl-keys .tl-kf", "els => els.map(e => +e.dataset.frame).sort((a, b) => a - b)")

    page.fill("#prompt", "thick white smoke")
    page.evaluate("document.activeElement.blur()")
    stroke(page, [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End")
    stroke(page, [(0.45, 0.3), (0.55, 0.2)])
    check(keys() == [0, 32], f"a keyframe on frame 0 and one on the last frame: {keys()}")
    page.keyboard.press("Home")
    page.keyboard.press("Control+c")
    for _ in range(9):
        page.keyboard.press("ArrowRight")
    page.keyboard.press("Control+v")
    check(keys() == [0, 9, 32], f"Ctrl+C on frame 0, Ctrl+V on frame 9 (8k + 1): {keys()}")
    tl = page.eval_on_selector("#timeline", "e => { const r = e.getBoundingClientRect(); return { x: r.x, w: r.width }; }")
    kf = page.eval_on_selector("#tl-keys .tl-kf[data-frame='9']", "e => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; }")
    page.mouse.move(kf["x"], kf["y"]); page.mouse.down()
    page.mouse.move(tl["x"] + (17.5 / 33) * tl["w"], kf["y"], steps=6); page.mouse.up()
    check(keys() == [0, 17, 32], f"dragging a diamond moves its keyframe along the grid: {keys()}")
    page.keyboard.press("Delete")
    check(keys() == [0, 32], f"Delete removes the keyframe on the playhead: {keys()}")
    page.keyboard.press("Control+z")
    check(keys() == [0, 17, 32], f"Ctrl+Z brings it back: {keys()}")
    page.keyboard.press("Enter")
    page.wait_for_function("""(() => { const r = document.querySelector('#history li[data-id="fluid"]');
      return !!r && !r.classList.contains('busy') && document.querySelector('#fluid').hidden; })()""", timeout=120000)
    log = log_lines(page)
    sent = [line for line in log if line.startswith("Fluid v1: 3 keyframe")]
    check(sent and 'prompt "ainvfxfluid, thick white smoke"' in sent[0] and "at 1, 18, 33," in sent[0],
          f"Enter generates with the trigger, the words and the three keyframes: {sent}")
    rows = row_titles(page)
    check(rows == ["1. Fluid"] and any("under the edits: the fluid shot v1" in line for line in log) and not page.is_disabled("[data-tool=erase]"),
          f"the fluid shot is the first edit and the plate under the next ones, with Clean and Light on: {rows}")
    page.click('#history li[data-id="fluid"] .edit')
    check(not page.is_hidden("#fluid"), "the pencil on the fluid row brings its keyframes back")
    page.keyboard.press("Enter")
    until(page, "document.querySelector('#hud').textContent.includes('already made')")
    log = log_lines(page)
    check(not any(line.startswith("Fluid v2") for line in log) and "already made" in page.text_content("#hud"),
          "Enter again on the same keyframes and words makes nothing twice")
    page.screenshot(path=os.path.join(SHOTS, "4_fluid.png"))
    page.keyboard.press("c")
    check(page.is_hidden("#fluid") and row_titles(page) == ["1. Fluid"],
          "another tool closes the keyframes: the fluid shot stays the first edit")
    page.click('#history li[data-id="fluid"] .eye')
    page.wait_for_function("[...document.querySelectorAll('#log li span')].some((e) => e.textContent.includes('under the edits: the blank plate'))", timeout=60000)
    page.click('#history li[data-id="fluid"] .eye')
    page.wait_for_function("[...document.querySelectorAll('#log li span')].filter((e) => e.textContent.includes('under the edits: the fluid shot v1')).length >= 2", timeout=60000)
    check(page.get_attribute('#history li[data-id="fluid"] .eye', "aria-pressed") == "true",
          "the eye on the fluid row bypasses it (the blank plate under the edits) and turns it back on (its shot)")

    # A paint edit on the fluid shot, then the scene saved and opened again: all of it comes back, from the job index
    page.keyboard.press("p")
    page.fill("#prompt", "a lantern"); page.evaluate("document.activeElement.blur()")
    stroke(page, [(0.2, 0.25), (0.3, 0.3)])
    page.evaluate(WATCH)
    page.keyboard.press("Enter")
    rows_done = """(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      const f = document.querySelector('#history li[data-id="fluid"] small');
      return t.join() === '2. Paint,1. Fluid' && !document.querySelector('#history li.busy') && !!f && f.textContent.includes('thick white smoke'); })()"""
    page.wait_for_function(rows_done, timeout=120000)
    page.wait_for_function(f"window.__lines.some((t) => t.includes('{REVIEWED}'))", timeout=120000)  # its render made, through the full-size composite
    name, scene = save_scene(page)
    check(scene["fluid"]["prompt"] == "thick white smoke" and scene["fluid"]["made"] and [e["prompt"] for e in scene["edits"]] == ["a lantern"],
          f"the scene keeps the fluid shot's own words, that it was made, and the edit on it: {scene['fluid']['prompt']!r}, {[e['prompt'] for e in scene['edits']]}")

    page.evaluate(WATCH)
    open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=120000)
    page.wait_for_function(rows_done, timeout=120000)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('review: made before') || t.startsWith('review '))", timeout=120000)
    grew = added(page, ("ingest", "fluid", "edit", "shot", "matte", "comp", "review"))
    posted = {k: v for k, v in grew.items() if k.endswith("posted") and v}
    check(not posted and all(grew[f"{s}: made before"] >= 1 for s in ("fluid", "edit", "shot", "review")),
          f"the scene opens again as it was: the fluid shot, the edit and every render step from the job index, nothing run twice: {grew}")
    check(not errors, f"no console errors in the fluid shot: {errors}")
    page.close()


def scene_flow(browser, port):
    """A plate with a paint and a whole-object erase, saved as a scene and opened again: every job from the job index."""
    page = load(browser, port)
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    open_plate(page)

    def reviews(n):  # the full-size composite of the edits on show, the last step Generate starts
        page.wait_for_function(f"window.__lines.filter((t) => t.includes('{REVIEWED}')).length >= {n}", timeout=180000)

    page.evaluate(WATCH)
    page.keyboard.press("p")
    page.fill("#prompt", "a red fire"); page.evaluate("document.activeElement.blur()")
    stroke(page, [(0.3, 0.6), (0.35, 0.65)])
    page.keyboard.press("Enter")
    page.wait_for_function("""(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      return t.join() === '1. Paint' && !document.querySelector('#history li.busy'); })()""", timeout=120000)
    reviews(1)  # each set of edits renders to its export before the next edit, so the scene's every step is made once
    page.keyboard.press("c")
    seen = len(log_lines(page))
    page.fill("#prompt", "the cup"); page.evaluate("document.activeElement.blur()")
    stroke(page, [(0.6, 0.4), (0.62, 0.45)])
    rested(page, seen)
    page.keyboard.press("Enter")
    page.wait_for_function("""(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      return t.join() === '2. Clean,1. Paint' && !document.querySelector('#history li.busy'); })()""", timeout=120000)
    reviews(2)
    settled(page)
    name, _ = save_scene(page)
    page.evaluate(WATCH)
    open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=120000)
    page.wait_for_function("""(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      return t.join() === '2. Clean,1. Paint' && !document.querySelector('#history li.busy'); })()""", timeout=120000)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('review: made before') || t.startsWith('review '))", timeout=180000)
    settled(page)
    grew = added(page, ("ingest", "prompt", "edit", "clean", "cleanup", "shot", "matte", "comp", "review"))
    posted = {k: v for k, v in grew.items() if k.endswith("posted") and v}
    check(not posted and grew["edit: made before"] >= 2 and grew["review: made before"] >= 1,
          f"a plate's scene opens again from the job index: the edits and every render step, nothing run twice: {grew}")
    check(not errors, f"no page errors in the scene: {errors}")
    page.close()


def ocio_flow(browser, port):
    """The OCIO menu on the right-click: another view, then another plate colour space, at once; the second is made again."""
    page = load(browser, port)
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
    centre = "(() => { const c = document.querySelector('#view'); return [...c.getContext('2d').getImageData(c.width >> 1, c.height >> 1, 1, 1).data.slice(0, 3)]; })()"
    pixel = lambda: page.evaluate(centre)  # noqa: E731
    differs, same = f"(was) => {centre}.some((v, i) => v !== was[i])", f"(was) => {centre}.every((v, i) => Math.abs(v - was[i]) <= 2)"  # the centre pixel against an earlier read
    exact = "document.querySelector('#view').dataset.precision === 'float'"  # paused, a video plate shows its source frame
    page.wait_for_function(exact, timeout=30000)
    before = pixel()
    page.evaluate(WATCH)
    menu(page, "OCIO", "View: Un-tone-mapped", "ACES 2.0 - SDR 100 nits (Rec.709)")
    page.wait_for_function("window.__lines.some((t) => t.startsWith('OCIO view: sRGB - Display: ACES 2.0'))", timeout=10000)
    until(page, differs, arg=before)
    aces = pixel()
    check(aces != before, f"another view applies at once: the same frame through ACES 2.0 SDR, {before} becomes {aces}")
    page.keyboard.press("Space")  # while it plays
    menu(page, "OCIO", "View: ACES 2.0 - SDR 100 nits (Rec.709)", "Un-tone-mapped")
    page.keyboard.press("Space")
    page.keyboard.press("Home")
    page.wait_for_function(exact, timeout=30000)
    until(page, same, arg=before)
    check(max(abs(a - b) for a, b in zip(pixel(), before)) <= 2, "back to Un-tone-mapped while it plays, the frame looks as it did")
    menu(page, "OCIO", "Colour space: sRGB Encoded Rec.709 (sRGB), from file", "Utility", "Linear Rec.709 (sRGB)")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('Linear Rec.709 (sRGB)') && document.querySelector('#opening').hidden", timeout=60000)
    until(page, differs, arg=before)
    until(page, "window.__lines.some((t) => t.startsWith('ingest '))")
    lines, linear = page.evaluate("window.__lines"), pixel()
    said = [t for t in lines if t.startswith("Plate colour space") or t.startswith("ingest ")]
    check(any(t.startswith("Plate colour space: Linear Rec.709 (sRGB)") for t in said) and any(t.startswith("ingest ") for t in said) and linear != before,
          f"another plate colour space: the viewer shows it, and the plate opens again in it for the models and the export: {before} becomes {linear}; {said}")
    menu(page, "OCIO", "Colour space: Linear Rec.709 (sRGB), override", "Utility", "sRGB Encoded Rec.709 (sRGB)")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('sRGB Encoded Rec.709 (sRGB)') && document.querySelector('#opening').hidden", timeout=60000)
    check(not errors, f"no page errors with OCIO: {errors}")
    page.close()


def race_flow(browser, port):
    """Generate pressed while the render of the edit before it starts, before its first step. On a plate just opened, the
    page's running step was a stale { phase } object, so preempt() threw, and the new edit was listed but never made
    (from 0.4.10; the live CI job of 0.5.7). The mock holds the render's first upload for 4 s, so the press lands there.
    The flow's mock serves this page alone, so no other page's upload takes the hold."""
    page = load(browser, port)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    base = page.url.split("/extensions/")[0]
    open_plate(page)

    def edit(words, pts):
        paint_once(page, words, pts)
        page.keyboard.press("Enter")

    made = klein_passes(page)
    edit("a blue lamp", [(0.62, 0.3), (0.7, 0.34)])
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    since = time.time()
    urllib.request.urlopen(urllib.request.Request(f"{base}/mock/slow", json.dumps({"seconds": 4, "times": 1}).encode(),
                                                  {"Content-Type": "application/json"}))
    for _ in range(50):  # the render of edit 1 starts 0.3 s after it, with its first upload, which the mock holds
        if any(e[0] == "slow upload" and e[1] >= since for e in json.loads(urllib.request.urlopen(f"{base}/mock/events").read())):
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the render's first upload never reached the mock: the race was not set up")
    page.keyboard.press("n")
    edit("a green bottle", [(0.2, 0.7), (0.28, 0.74)])
    poll(page, lambda: errors or klein_passes(page) >= made + 2, 60)  # the new edit's Klein pass, or the page error the old code threw
    check(not errors, f"Generate while the render before it starts, before its first step: no page error {errors}")
    page.wait_for_function(DONE.format(n=2), timeout=120000)
    page.wait_for_function(f"[...document.querySelectorAll('#log li span')].filter((e) => e.textContent.includes('Klein quick pass')).length >= {made + 2}",
                           timeout=60000)
    check(klein_passes(page) == made + 2, f"and the new edit is made, as the one before: {klein_passes(page) - made} Klein passes")
    page.close()


def oom_flow(browser, port):
    """The GPU runs out of memory once (the mock's /mock/oom): the page frees ComfyUI's memory, waits until it is released,
    then runs the fluid shot again. Posted at once, the retry ran before ComfyUI freed anything and ran out again (29 Oct)."""
    page = load(browser, port)
    base = page.url.split("/extensions/")[0]
    urllib.request.urlopen(urllib.request.Request(f"{base}/mock/oom", json.dumps({"workflow": "fluid", "times": 1}).encode(),
                                                  {"Content-Type": "application/json"}))
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8")  # an 8-bit fluid shot: fluid16_flow covers 16-bit, the default once SDR to HDR is installed
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    stroke(page, [(0.45, 0.7), (0.55, 0.6)])
    page.evaluate("document.activeElement.blur()"); page.keyboard.press("Enter")
    page.wait_for_function("""(() => { const r = document.querySelector('#history li[data-id="fluid"]');
      return !!r && !r.classList.contains('busy') && document.querySelector('#fluid').hidden; })()""", timeout=120000)
    ev = json.loads(urllib.request.urlopen(f"{base}/mock/events").read())
    oom, free, posted = [e for e in ev if e[0] == "oom"], [e for e in ev if e[0] == "free"], [e for e in ev if e[0] == "prompt"]
    waited = len(posted) >= 2 and len(free) == 1 and posted[-1][1] >= free[0][1] + 1.0
    check(len(oom) == 1 and waited, f"out of memory once: the page frees ComfyUI's memory, waits until it is released, then makes the shot: "
          f"{[(e[0], round(e[1] - ev[0][1], 2)) for e in ev]}")
    page.close()


def key_ranges(doc):
    """The Keys dialog's ranges spelled out, key by key: « 1 to 8 » gives 1, 2, ... 8, « Shift+2 to Shift+8 » gives
    Shift+2, Shift+3, ... Shift+8. A range's two ends carry the same modifiers."""
    def spell(m):
        a, i, b, j = m.group(1), m.group(2), m.group(3), m.group(4)
        if a != b or i > j or i.isdigit() != j.isdigit(): return m.group(0)
        return ", ".join(f"{a}{chr(c)}" for c in range(ord(i), ord(j) + 1))
    return re.sub(r"(?<![\w+])((?:[A-Za-z]+\+)*)([0-9]|[A-Z]) to ((?:[A-Za-z]+\+)*)([0-9]|[A-Z])(?![\w])", spell, doc)


def keys_flow(browser, port):
    """Every key the Keys dialog documents does what it says, and every key the menu shows is in the Keys dialog."""
    page = load(browser, port)
    open_plate(page)
    doc = key_ranges(page.evaluate("[...document.querySelectorAll('#help dt')].map((e) => e.textContent).join(' | ')"))  # the keys column
    page.click("#view", button="right")
    keys = page.evaluate("[...new Set([...document.querySelectorAll('#ctx kbd')].map((k) => k.textContent).filter(Boolean))]")
    page.keyboard.press("Escape")
    undocumented = [k for k in keys if not re.search(rf"(?<![A-Za-z]){re.escape(k.split('+')[-1])}(?![A-Za-z])", doc, re.I)]
    check(keys and not undocumented, f"every key in the right-click menu is in the Keys dialog: {undocumented or len(keys)}")
    page.evaluate("document.activeElement.blur()")
    text = lambda q: page.text_content(q)  # noqa: E731
    attr = lambda q, a: page.get_attribute(q, a)  # noqa: E731
    frame = lambda: int(text("#frame-now"))  # noqa: E731
    results = {}

    def key(k, test):  # a key's effect, within 1.5 s: a busy page answers later than at once
        page.keyboard.press(k)
        results[k] = poll(page, test, 1.5)
    page.keyboard.press("Home"); start = frame()
    key("ArrowRight", lambda: frame() == start + 1); key("ArrowLeft", lambda: frame() == start)
    key("End", lambda: frame() == int(text("#frame-total").strip("/ "))); key("Home", lambda: frame() == start)
    key("Space", lambda: "playing" in attr("#play-btn", "class")); page.keyboard.press("Space")
    key("ArrowDown", lambda: "playing" in attr("#play-btn", "class")); page.keyboard.press("ArrowDown")
    key("]", lambda: "Out point" in text("#hud")); key("[", lambda: "In point" in text("#hud")); key("\\", lambda: "cleared" in text("#hud"))
    key("F6", lambda: attr("#wipe-btn", "aria-pressed") == "true"); page.keyboard.press("F6")
    key("1", lambda: text("#hud") == "1:1"); key("f", lambda: text("#hud") == "Fit")
    key("c", lambda: "on" in attr("[data-tool=erase]", "class")); key("l", lambda: "on" in attr("[data-tool=light]", "class"))
    key("p", lambda: "on" in attr("[data-tool=paint]", "class"))
    size = int(text("#size-out")); key("=", lambda: int(text("#size-out")) > size); key("-", lambda: int(text("#size-out")) == size)
    key("x", lambda: attr("#rub-btn", "aria-pressed") == "true"); page.keyboard.press("x")
    key("i", lambda: page.evaluate("document.querySelector('#view').classList.contains('picking')")); page.keyboard.press("Escape")  # the in-frame picker
    for k, name in (("Shift+E", "Exposure"), ("k", "Contrast"), ("y", "Gamma"), ("Shift+S", "Saturation"), ("h", "Hue")):
        key(k, lambda name=name: text("#hud").startswith(name)); page.keyboard.press("Escape")
    key("Shift+E", lambda: True); key("=", lambda: text("#display-state").startswith("E +0.1")); key("Backspace", lambda: page.is_hidden("#display-state"))
    page.keyboard.press("Escape")
    key("Shift+E", lambda: True); key("=", lambda: text("#display-state").startswith("E +0.1")); page.keyboard.press("Escape")
    key("Shift+Home", lambda: page.is_hidden("#display-state"))  # RV's Reset All Color
    for k, name in (("Shift+R", "Red"), ("Shift+G", "Green"), ("Shift+B", "Blue"), ("Shift+L", "Luminance")):
        key(k, lambda name=name: text("#display-state") == name)
    key("Shift+C", lambda: page.is_hidden("#display-state"))
    key("Shift+I", lambda: text("#display-state") == "Inverted"); page.keyboard.press("Shift+I")
    page.keyboard.down("o"); results["hold O"] = poll(page, lambda: text("#hud") == "Plate", 1.5); page.keyboard.up("o")
    key("?", lambda: page.evaluate("document.querySelector('#help').open")); key("?", lambda: not page.evaluate("document.querySelector('#help').open"))
    failed = [k for k, ok in results.items() if not ok]
    check(not failed, f"every documented key does what the Keys dialog says ({len(results)} presses): {failed or 'all'}")
    page.close()


def hdr_flow(browser, port):
    """SDR to HDR in Deliver. ?hdr=0 turns it off: an EXR plate offers no bit-depth pass, a blank plate no 16-bit. By default
    a video plate offers it, switched off, and an EXR plate runs it on its own, with no switch: after the full-size shot
    and before the full-size composite, its live preview in a corner naming its step of the pass's steps. Every finished
    pass with a picture is a row to click. Esc stops the render on its way and Enter goes on."""
    page = load(browser, port, "?blank=0&hdr=0")
    open_path(page, "paintaplate/hdr_room")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('EXR') && document.querySelector('#opening').hidden", timeout=60000)
    check(page.is_hidden("#deliver-hdr-row") and page.is_hidden("#deliver-auto") and page.evaluate("document.querySelector('#b-depth').closest('label').style.display") == "none",
          "?hdr=0 turns SDR to HDR off: Deliver offers no bit-depth pass, no 16-bit blank plate")
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    page.evaluate(WATCH)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    lines = lambda: page.evaluate("window.__lines")  # noqa: E731
    open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
    check(not page.is_hidden("#deliver-hdr-row") and not page.is_checked("#deliver-hdr"), "a video plate: Deliver offers SDR to HDR, off")
    open_path(page, "paintaplate/hdr_room")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('EXR') && document.querySelector('#opening').hidden", timeout=60000)
    check(page.is_hidden("#deliver-hdr-row") and not page.is_hidden("#deliver-auto"), "an EXR plate: SDR to HDR runs on its own, with no switch")
    page.evaluate(WATCH)
    page.keyboard.press("p")
    paint_once(page, "a red lamp", [(0.3, 0.6), (0.36, 0.7)])
    page.keyboard.press("Enter")
    page.wait_for_function("!document.querySelector('#live-inset').hidden", timeout=240000)
    caption = page.text_content("#live-inset figcaption")
    wait_log(page, added_line(REVIEWED), 240000, "full-size composite")
    check(bool(re.search(r"step \d+ of \d+", caption)) and page.is_hidden("#live-inset"),
          f"a full-size pass shows its live preview in a corner while the preview plays, then it goes: {caption}")
    new = lines()
    at = lambda text: next((i for i, line in enumerate(new) if text in line), None)  # noqa: E731
    check(at("SDR to HDR done in") is not None and at("SDR to HDR done in") < at(REVIEWED),
          "the full-size shot goes through SDR to HDR before the full-size composite the viewer plays")
    rows = lambda: page.eval_on_selector_all("#stages li.pick .name", "els => els.map(e => e.textContent)")  # noqa: E731
    shown = lambda: page.eval_on_selector_all("#stages li.shown .name", "els => els.map(e => e.textContent)")  # noqa: E731
    picture = lambda: page.evaluate("document.querySelector('canvas[data-picture]').dataset.picture")  # noqa: E731
    check({"First frame", "Shot, preview", "SDR to HDR", "Composite, full size"} <= set(rows()) and shown() == ["Composite, full size"],
          f"every finished pass with a picture is a row to click, the latest on show: {rows()}, {shown()}")
    page.click("#stages li.pick:has-text('SDR to HDR')")
    poll(page, lambda: shown() == ["SDR to HDR"])
    check(shown() == ["SDR to HDR"] and "on show" in (page.text_content("#hud") or ""), f"a click shows that pass in the viewer: {shown()}")
    page.click("#stages li.pick:has-text('First frame')")
    poll(page, lambda: shown() == ["First frame"] and picture() == "hero")
    check(shown() == ["First frame"] and picture() == "hero", f"the First frame row shows the edit as Klein made it: {shown()}, {picture()}")
    page.click("#stages li.pick:has-text('First frame')")
    poll(page, lambda: shown() == ["Composite, full size"])
    check(shown() == ["Composite, full size"], f"a second click goes back to the latest: {shown()}")
    page.evaluate(WATCH)
    page.keyboard.press("Control+Enter")  # another seed: a new edit pass, then a new render
    wait_log(page, "window.__lines.some((t) => /^Render v\\d+: .* \\(about \\d+ s\\)/.test(t))", 120000, "render step")
    stopped = lambda: any(line.startswith("Stopped") for line in lines())  # noqa: E731
    page.keyboard.press("Escape")
    poll(page, lambda: stopped() or "Esc again" in (page.text_content("#hud") or ""))
    if not stopped():  # Ctrl+Enter selected the edit: Esc deselects first
        check("Esc again stops generating" in page.text_content("#hud"), "with an edit selected, Esc deselects first and says a second Esc stops generating")
        page.keyboard.press("Escape")
    check(poll(page, lambda: stopped() and not page.is_disabled("#generate")),
          "Esc stops the render step on its way, and Generate can go on")
    page.evaluate(WATCH)
    page.keyboard.press("Enter")
    wait_log(page, added_line(REVIEWED), 240000, "full-size composite after Enter")
    check(True, "Enter goes on from where it stopped: the full-size composite is made")
    check(not errors, f"no console errors with SDR to HDR: {errors}")
    page.close()


def fluid16_flow(browser, port):
    """A blank plate asked in 16-bit: its fluid shot goes through SDR to HDR and opens as an EXR plate, the switch on."""
    page = load(browser, port)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.select_option("#b-depth", "16"); page.dispatch_event("#b-frames", "input")
    note = page.text_content("#b-note")
    check("16-bit: SDR to HDR" in note, f"the blank plate form says what 16-bit does: {note}")
    page.evaluate(WATCH)
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("Enter")
    wait_log(page, added_line("under the edits: the fluid shot v"), 240000, "the HDR fluid shot under the edits")
    page.wait_for_function("!document.querySelector('#deliver-auto').hidden", timeout=60000)
    new = page.evaluate("window.__lines")
    check(any(line.startswith("Plate ") and "16-bit" in line for line in new) and any("SDR to HDR done in" in line for line in new),
          "16-bit: the plate's line says so, and the fluid shot goes through SDR to HDR")
    check(not page.is_hidden("#deliver-auto"), "the HDR fluid shot is an EXR plate: SDR to HDR runs on its own for the edits on it")
    check(not page.is_disabled("#export-btn"), "a fluid shot with no edit on it can be exported")
    page.click("#export-btn")
    fmt = page.text_content("#x-format") or ""
    check("half-float EXR" in fmt and page.is_hidden("#x-matte"), f"its export is its HDR frames, without the render's options: {fmt}")
    with page.expect_download() as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    check(any(n.startswith("hdr/") and n.endswith(".exr") for n in names) and any(n.startswith("plate/") for n in names),
          f"the zip holds the HDR frames and the shot in the blank plate's format: {names[:3]}")
    page.evaluate("""() => { const v = document.querySelector('canvas[data-precision]'); window.__prec = [];
      new MutationObserver(() => window.__prec.push(v.dataset.precision)).observe(v, { attributes: true, attributeFilter: ['data-precision'] }); }""")
    page.click("#play-btn"); page.wait_for_function("window.__prec.length >= 34", timeout=30000); page.click("#play-btn")  # two rounds of its 17 frames
    seen = page.evaluate("window.__prec")
    flips = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
    check(flips <= 1, f"playing the HDR plate, its EXR frames and its 8-bit movie never alternate: {flips} changes in {len(seen)} draws")
    page.wait_for_function("document.querySelector('canvas[data-precision]').dataset.precision === 'float'", timeout=30000)
    check(True, "paused, the frame shows at full precision")
    check(not errors, f"no console errors in a 16-bit fluid shot: {errors}")
    page.close()


def layout_flow(browser, port):
    """The side panel and the log resize from their dividers, keep the stage usable, keep their sizes for the next session,
    and take their first size back on a double-click."""
    page = load(browser, port)
    open_plate(page)
    width = lambda: page.evaluate("document.querySelector('.side').offsetWidth")
    height = lambda: page.evaluate("document.querySelector('#log').offsetHeight")
    frame = lambda: page.evaluate("document.querySelector('#viewport').getBoundingClientRect().toJSON()")
    stage = lambda: page.evaluate("document.querySelector('.stage').getBoundingClientRect().toJSON()")
    check(page.locator("#split-log").is_hidden(), "the log's divider shows only with the log open")
    w0, v0 = width(), frame()
    drag(page, "#split-side", -120, 0)
    w1, v1 = width(), frame()
    check(w1 == w0 + 120 and round(v0["width"] - v1["width"]) == 120, f"the side divider dragged 120 px left: History {w0} to {w1} px, the frame 120 px narrower")
    drag(page, "#split-side", -3000, 0)
    check(stage()["width"] >= 319, f"dragged to the far left, the stage keeps its room: {round(stage()['width'])} px")
    drag(page, "#split-side", 3000 + 120, 0)
    check(width() == 220, f"dragged to the far right, History keeps its least, 220 px: {width()}")
    drag(page, "#split-side", -(w1 - 220), 0)
    if page.evaluate("document.querySelector('#log').hidden"):
        page.click("#log-btn")
    h0 = height()
    drag(page, "#split-log", 0, -150)
    h1 = height()
    check(h1 == h0 + 150, f"the log's divider dragged 150 px up: the log {h0} to {h1} px")
    page.focus("#split-log"); page.keyboard.press("ArrowUp")
    check(height() == h1 + 16, f"an arrow key on a focused divider moves it 16 px: {height()}")
    drag(page, "#split-log", 0, -3000)
    check(stage()["height"] >= 319, f"dragged to the top, the stage keeps its room: {round(stage()['height'])} px")
    drag(page, "#split-log", 0, 3000)
    page.focus("#split-log"); [page.keyboard.press("ArrowUp") for _ in range(2)]
    h2 = height()
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=20000)
    page.click("#log-btn")
    check((width(), height()) == (w1, h2), f"a new session keeps the dragged sizes: History {width()} px, the log {height()} px")
    page.dblclick("#split-side"); page.dblclick("#split-log")
    check((width(), height()) == (288, 180), f"a double-click gives the first sizes back: {width()} and {height()} px")
    page.close()


def close_flow(browser, port):
    """The × after the plate's name closes it: its renders stop, its frames leave memory, the page is empty and says so, also
    when the model warm-up ends after the close (3 Nov: the warm-up's « Ready: every model loaded » replaced « Plate closed »
    when it ended after the close). The mock holds the warm-up's first upload until the plate is closed, so the close lands
    inside the warm-up every time, on any machine. A failed check prints the page's state."""
    base = f"http://127.0.0.1:{port}"
    urllib.request.urlopen(urllib.request.Request(f"{base}/mock/slow", json.dumps({"seconds": 120, "times": 1}).encode(),
                                                  {"Content-Type": "application/json"}))
    page = load(browser, port)  # a new warm-up, its first upload held
    page.evaluate(WATCH)
    check(poll(page, lambda: any(e[0] == "slow upload" for e in mock_route(port, "/mock/events")), 30),
          "the warm-up's first upload is the one the mock holds, before the plate opens")
    page.click("#open-btn")
    page.click("#open .tabs [data-tab='files']")
    page.fill("#path", "plates/desk.mp4")
    page.click("#open-go")
    try:  # flows side by side, one per CPU (32 on the laptop in Chrome, 12 Nov): the open takes longer than alone
        page.wait_for_selector("#close-btn", state="visible", timeout=60000)
    except Exception as exc:  # Playwright's TimeoutError: the check says what the page and the mock show
        if type(exc).__name__ != "TimeoutError":
            raise
        check(False, f"the plate opens and its × shows within 60 s{page_state(page)}, mock events {mock_route(port, '/mock/events')[-6:]}")
    page.click("#close-btn")
    page.wait_for_function("!document.querySelector('#empty').hidden", timeout=5000)
    ok = (page.is_hidden("#close-btn") and not page.text_content("#spec") and "Plate closed" in page.text_content("#status")
          and page.is_disabled("#play-btn"))
    check(ok, "the × after the plate's name closes it: the page is empty again and says the frames are freed" + ("" if ok else page_state(page)))
    urllib.request.urlopen(urllib.request.Request(f"{base}/mock/release", b"{}", {"Content-Type": "application/json"}))
    end = "/every model loaded|Model warm-up done/.test(t)"  # the warm-up's last line: on the status line, or in the log only
    wait_log(page, f"window.__lines.some((t) => {end})", 30000, "end of the model warm-up")
    after = page.evaluate(f"""(() => {{ const l = window.__lines, c = l.findIndex((t) => t.includes('closed: renders stopped'));
      return c >= 0 && l.findIndex((t) => {end}) > c; }})()""")
    ok = after and "Plate closed" in page.text_content("#status")
    check(ok, "the model warm-up ends after the close: « Plate closed » stays on the status line, the warm-up's line goes to the log"
          + ("" if ok else page_state(page)))
    page.close()


def phone_flow(browser, port):
    """The page on a phone, upright and on its side: the frame, the transport, the menu and the log fit the screen."""
    first = load(browser, port)  # a first session opens the plate, so each phone's session finds its ingest in the job index
    open_plate(first)
    for name, size in (("upright", {"width": 390, "height": 844}), ("sideways", {"width": 844, "height": 390})):
        page = browser.new_page(viewport=size, is_mobile=True, has_touch=True, device_scale_factor=3)
        page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
        page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=20000)
        page.click("#open-btn"); page.fill("#path", "plates/desk.mp4"); page.click("#open-go")
        page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
        until(page, "[...document.querySelectorAll('#log li span')].some((e) => e.textContent.includes('ingest: made before'))")
        logged = log_lines(page)
        check(any("ingest: made before with the same inputs, taken from the job index" in line for line in logged),
              f"{name} phone: the plate opened again in a new session comes from the job index, with no new ingest")
        fits = page.evaluate("""() => { const W = innerWidth, H = innerHeight, r = (q) => document.querySelector(q).getBoundingClientRect();
          const inside = (q) => { const b = r(q); return b.left >= -1 && b.right <= W + 1 && b.top >= -1 && b.bottom <= H + 1 && b.width > 0; };
          return { sideways: document.documentElement.scrollWidth <= W, view: inside('#view'), play: inside('#play-btn'), timeline: inside('#timeline'),
                   generate: inside('#generate'), status: inside('#status'), menu: inside('#menu-btn') }; }""")
        check(all(fits.values()), f"{name} phone: the frame, Generate, the transport, the status line and the menu button fit the screen {fits}")
        page.tap("#menu-btn")
        page.tap("#ctx > li:has(> span:first-child:text-is('Control'))")
        sheet = page.evaluate("""() => { const b = document.querySelector('#ctx').getBoundingClientRect(), s = document.querySelector('#ctx .group.open .sub');
          return { sheet: document.querySelector('#ctx').classList.contains('sheet'), inside: b.left >= 0 && b.right <= innerWidth && b.bottom <= innerHeight && b.top >= 0,
                   open: !!s && s.getBoundingClientRect().width > 0 }; }""")
        page.screenshot(path=os.path.join(SHOTS, f"6_phone_{name}_menu.png"))
        check(all(sheet.values()), f"{name} phone: the menu opens as a sheet on the screen, a tap opens a group {sheet}")
        page.tap("#ctx .sub button:has-text('Play or pause')")
        check(page.is_hidden("#ctx"), f"{name} phone: an action in the sheet runs and closes it")
        page.tap("#log-btn")
        log = page.evaluate("() => { const b = document.querySelector('#log').getBoundingClientRect(); return b.top >= 0 && b.bottom <= innerHeight + 1 && b.height > 20; }")
        page.screenshot(path=os.path.join(SHOTS, f"6_phone_{name}_log.png"))
        check(log, f"{name} phone: the open log fits the screen")
        page.close()
    first.close()


FLOWS = {"start": start_flow, "open": open_flow, "colour": colour_flow, "generate": generate_flow, "history": history_flow,
         "one_edit": one_edit_flow, "fluid": fluid_flow, "scene": scene_flow, "ocio": ocio_flow, "race": race_flow, "keys": keys_flow,
         "oom": oom_flow, "hdr": hdr_flow, "fluid16": fluid16_flow, "layout": layout_flow, "close": close_flow, "phone": phone_flow}


def module_flow(name):
    """The flow of tests/flows/<name>.py: its run(browser, port, U), U being this module (check, WATCH, paint_once...)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"flows_{name}", os.path.join(HERE, "flows", f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return lambda browser, port: module.run(browser, port, sys.modules[__name__])


def flow_names(shard=""):
    """Every flow, in the order of a run: the flows of this file, then one per module of tests/flows, by name. A shard,
    "2/4", is every fourth flow from the second: the parts hold different flows and, together, all of them."""
    folder = os.path.join(HERE, "flows")
    extra = sorted(n[:-3] for n in os.listdir(folder) if n.endswith(".py") and not n.startswith("_")) if os.path.isdir(folder) else []
    twice = sorted(set(extra) & set(FLOWS))
    if twice:
        raise SystemExit(f"tests/flows: {', '.join(twice)} is also the name of a flow of ui_mock.py; rename the file")
    names = [*FLOWS, *extra]
    if shard:
        part, parts = (int(n) if n.isdigit() else 0 for n in (shard.split("/") + ["", ""])[:2])
        if not 1 <= part <= parts:
            raise SystemExit(f'a shard reads "2/4", the second of four parts: {shard}')
        names = names[part - 1::parts]
    return names


# ---------- The plates, made once for a run and copied into each flow's folders ----------

def make_hdr_plate(root):
    """An EXR plate with values above white for the SDR-to-HDR checks: 17 frames, a sun moving across a gradient."""
    import numpy as np, OpenEXR
    seq = os.path.join(root, "input", "paintaplate", "hdr_room")
    os.makedirs(seq, exist_ok=True)
    yy, xx = np.mgrid[0:352, 0:640].astype(np.float32)
    for k in range(17):
        img = np.stack([xx / 640, yy / 352, np.full_like(xx, 0.25)], -1) * 0.8
        img[(xx - 420 - 4 * k) ** 2 + (yy - 110) ** 2 < 30 ** 2] = 6.0
        OpenEXR.File({"compression": OpenEXR.PIZ_COMPRESSION, "type": OpenEXR.scanlineimage}, {"RGB": img.astype(np.float16)}).write(
            os.path.join(seq, f"room.{1001 + k}.exr"))


def make_plates(root):
    """The plates the flows open, under root/input: plates/desk.mp4 (the mock's own video plate), paintaplate/hdr_test (two
    EXR frames with values above white, for the frame route) and paintaplate/hdr_room (an EXR plate, make_hdr_plate)."""
    import numpy as np, OpenEXR
    sys.path.insert(0, HERE)
    import mock_comfy
    mock_comfy.make_plate(os.path.join(root, "input", "plates", "desk.mp4"))
    hdr = os.path.join(root, "input", "paintaplate", "hdr_test")
    os.makedirs(hdr, exist_ok=True)
    img = np.zeros((32, 64, 3), np.float16)
    img[:, :32], img[:, 32:] = 4.0, 0.5
    for n in (1001, 1002):
        OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}, {"RGB": img}).write(os.path.join(hdr, f"f.{n}.exr"))
    make_hdr_plate(root)


# ---------- The run: one process per flow, then the table ----------

def run_flow(name, port, root, plates, speed):
    """--flow: one flow in this process, against its own mock ComfyUI and its own browser."""
    from playwright.sync_api import sync_playwright
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(os.path.join(plates, "input"), os.path.join(root, "input"))
    os.makedirs(SHOTS, exist_ok=True)
    with open(os.path.join(SHOTS, f"mock_{name}.log"), "w") as log:
        mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_comfy.py"), "--port", str(port), "--root", root, "--speed", str(speed)], stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/system_stats", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("the mock ComfyUI did not start")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL") or None)
            (FLOWS.get(name) or module_flow(name))(browser, port)
            browser.close()
    finally:
        mock.terminate()


def stop(proc, stopped):
    """A flow past its limit: its process ends, with its mock and its browser."""
    stopped.append(True)
    os.killpg(proc.pid, signal.SIGKILL) if hasattr(os, "killpg") else proc.kill()


def run_child(name, port, a, plates, live, printing):
    """One flow in its own process. Alone, its lines print as they come; side by side with others, together at its end."""
    cmd = [sys.executable, os.path.abspath(__file__), "--flow", name, "--port", str(port), "--root", os.path.join(a.root, name), "--plates", plates, "--speed", str(a.speed)]
    t0, lines, stopped = time.time(), [], []
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    timer = threading.Timer(a.limit, stop, [proc, stopped])
    timer.start()
    if live:
        print(f"== {name}", flush=True)
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))
        if live:
            print(lines[-1], flush=True)
    code = proc.wait()
    timer.cancel()
    seconds, checks = time.time() - t0, sum(line.startswith("  ok   ") for line in lines)
    failure = None
    if stopped:
        failure = f"stopped after {a.limit} s (--limit)"
    elif code:
        failure = next((line[7:] for line in lines if line.startswith("  FAIL ")), f"its process ended with code {code}")
    with printing:
        if not live:
            print("\n".join([f"== {name}", *lines]))
        print(f"== {name}: {checks} checks in {seconds:.0f} s, {'FAILED' if failure else 'passed'}", flush=True)
    return {"flow": name, "checks": checks, "seconds": round(seconds, 1), "failure": failure, "lines": lines}


def table(results, wall, jobs):
    width = max(len(r["flow"]) for r in results)
    print(f"\n{'flow':<{width}}  checks    time  result")
    for r in results:
        print(f"{r['flow']:<{width}}  {r['checks']:>6}  {r['seconds']:>4.0f} s  " + (f"FAILED: {r['failure']}" if r["failure"] else "passed"))
    failed = [r["flow"] for r in results if r["failure"]]
    print(f"{len(results)} flows, {sum(r['checks'] for r in results)} checks passed, {sum(r['seconds'] for r in results):.0f} s of flows in "
          f"{wall:.0f} s with {jobs} at a time" + (f"; failed: {', '.join(failed)}" if failed else ""))
    print("UI MOCK FAILED" if failed else "UI MOCK PASSED")


def main():
    ap = argparse.ArgumentParser(description="The page against the mock ComfyUI, flow by flow.")
    ap.add_argument("--list", action="store_true", help="name the flows and stop")
    ap.add_argument("--only", default="", help="run these flows only: names from --list, separated by commas")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="how many flows run side by side (default: one per CPU)")
    ap.add_argument("--shard", default="", help='one part of the flows, as "2/4": the second of four parts')
    ap.add_argument("--json", help="write every flow's result to this file: its checks, its time, its failure, its lines")
    ap.add_argument("--limit", type=int, default=600, help="seconds a flow may take before it is stopped and counted as failed")
    ap.add_argument("--speed", type=float, default=8, help="divide the simulated time of the mock's jobs by this (1: as mock_comfy.py runs alone)")
    ap.add_argument("--port", type=int, default=8199, help="the first mock's port; flows side by side take the next ones")
    ap.add_argument("--root", default="/tmp/paintaplate_mock_ui", help="where the mocks keep their folders, one per flow")
    ap.add_argument("--flow", help=argparse.SUPPRESS)  # the runner's own: one flow in this process
    ap.add_argument("--plates", help=argparse.SUPPRESS)  # the runner's own: where it made the plates
    a = ap.parse_args()
    if a.flow:
        try:
            run_flow(a.flow, a.port, a.root, a.plates, a.speed)
        except Exception as exc:
            if CHECKS["failed"] is None:  # not a failed check: a wait that ran out, a page that closed
                traceback.print_exc()
                print(f"  FAIL {type(exc).__name__}: {(str(exc).strip() or 'no message').splitlines()[0]}", flush=True)
            sys.exit(1)
        return
    names = flow_names(a.shard)
    if a.list:
        return print("\n".join(names))
    if a.only:
        picked = [n.strip() for n in a.only.split(",") if n.strip()]
        unknown = [n for n in picked if n not in flow_names()]
        if unknown:
            ap.error(f"no flow named {', '.join(unknown)}; --list names them")
        names = picked
    shutil.rmtree(a.root, ignore_errors=True)
    plates = os.path.join(a.root, "_plates")
    make_plates(plates)
    jobs = max(1, min(a.jobs, len(names)))
    ports, printing = queue.SimpleQueue(), threading.Lock()
    for k in range(jobs):
        ports.put(a.port + k)

    def one(name):
        port = ports.get()
        try:
            return run_child(name, port, a, plates, jobs == 1, printing)
        finally:
            ports.put(port)

    t0 = time.time()
    with ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(one, names))
    table(results, time.time() - t0, jobs)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(results, f, indent=1)
    sys.exit(1 if any(r["failure"] for r in results) else 0)


if __name__ == "__main__":
    main()
