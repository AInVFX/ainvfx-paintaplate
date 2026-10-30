"""The page's behaviour in headless Chromium against tests/mock_comfy.py: no ComfyUI, no GPU, about two minutes.

    python tests/ui_mock.py [--port 8199] [--keep]

Opens a plate from the plate browser, paints two edits, removes one, undoes and redoes, selects an edit and retypes its
words, tries another seed with Ctrl+Enter, undoes three steps, changes the preview size, uses the viewer's colour and the
right-click menu, and checks the log. Then one edit at a time: new words and more strokes change the edit just made, and
New edit (the N key, the button, the menu) or another tool starts a new one. Then a fluid shot: a blank plate, keyframes painted, copied, pasted, dragged,
deleted and brought back, generated, and opened as the plate. Prints UI MOCK PASSED at the end; tests/test_ui_mock.py
runs it. Screenshots go to /tmp/paintaplate_ui_mock.
"""
import re
import argparse, json, os, shutil, subprocess, sys, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SHOTS = "/tmp/paintaplate_ui_mock"
DONE = "document.querySelectorAll('#history li').length === {n} && !document.querySelector('#history li.busy')"


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        raise AssertionError(what)


def flow(page, port):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("response", lambda r: errors.append(f"{r.status}: {r.url}") if r.status >= 400 else None)
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=20000)
    version = page.text_content("#version") or ""
    first = page.eval_on_selector_all("#log li span", "els => els.slice(0, 3).map(e => e.textContent)")
    check(version.count(".") == 2 and f"AInVFX Paint a plate {version}" in first, f"the top bar shows the pack's version and the log names it first: {version} {first}")

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
    hdr = page.evaluate("""async () => { // an EXR through the frame route and the viewer's shader, as the colour tools see it
      const [{ Display }, { DISPLAY }] = await Promise.all(["display.mjs", "logic.mjs"].map((m) => import(new URL(m, location.href).href)));
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
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps')", timeout=60000)
    page.wait_for_function("/Describe the edit|Ready to play/.test(document.querySelector('#status').textContent)", timeout=60000)
    menu = page.eval_on_selector_all("#preview-size option", "els => els.map(e => e.textContent)")
    check(any("Fast · 640 × 352 (1/2)" in m for m in menu) and menu[0].startswith("Full"), f"the preview menu comes from the plate: {menu}")
    page.screenshot(path=os.path.join(SHOTS, "1_open.png"))
    box = page.eval_on_selector("#view", "e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }")

    def stroke(pts):
        page.mouse.move(box["x"] + pts[0][0] * box["w"], box["y"] + pts[0][1] * box["h"])
        page.mouse.down()
        for x, y in pts[1:]:
            page.mouse.move(box["x"] + x * box["w"], box["y"] + y * box["h"], steps=5)
        page.mouse.up()

    def titles():
        return page.eval_on_selector_all("#history li .title", "els => els.map(e => e.textContent)")

    def words():
        return page.eval_on_selector_all("#history li small", "els => els.map(e => e.textContent)")

    def passes():  # Klein passes run so far: a result used again adds none
        return sum("Klein quick pass" in line for line in page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)"))

    page.fill("#prompt", "a red fire")
    stroke([(0.3, 0.5), (0.4, 0.52), (0.5, 0.5)])
    stroke([(0.3, 0.6), (0.5, 0.62)])
    check(not page.is_disabled("#undo-btn"), "undo is live after a stroke")
    page.wait_for_timeout(2500)
    check(titles() == [] and not page.is_disabled("#generate"), f"the strokes wait for Generate: nothing starts by itself {titles()}")
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check(titles() == ["1. Paint"] and words() == ["a red fire"], f"Enter generates edit 1 with its words: {titles()} {words()}")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=120000)
    lines = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    full = [i for i, line in enumerate(lines) if "plays the full-size shot" in line]
    done = [i for i, line in enumerate(lines) if REVIEWED in line]
    check(bool(full and done) and full[-1] < done[-1] and not any(line.startswith("Export v") for line in lines),
          f"Generate makes the full-size composite and nothing for compositing software: the full-size shot plays, then the review: {full} {done}")
    with page.expect_download(timeout=120000) as dl:
        page.click("#export-btn"); page.click("#x-go")
    zipped = zipfile.ZipFile(dl.value.path()).namelist()
    lines = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    check(any(n.startswith("export/") for n in zipped) and any(n.startswith("matte/") for n in zipped) and any(line.startswith("Export v") for line in lines),
          f"Export writes the result and its matte when pressed, then the zip downloads: {sorted({n.split('/')[0] for n in zipped})}")
    # The ComfyUI graph: the scene as one workflow, in numbered sections in the order they run, each opening with a README
    with page.expect_download(timeout=60000) as dl:
        page.click("#export-btn"); page.click("#x-graph")
    graph = json.load(open(dl.value.path()))
    notes = [n["_meta"]["title"] for _, n in sorted(graph.items(), key=lambda kv: int(kv[0])) if n["class_type"] == "PrimitiveStringMultiline"]
    overview = graph[min(graph, key=int)]["inputs"]["value"]
    check(notes[:3] == ["README · How this graph works", "README · INPUT", "README · MODELS"] and any(t.startswith("README · EDIT 1 · ") for t in notes)
          and notes[-1] == "README · OUTPUT" and f"Paint a plate {page.text_content('#version')}" in overview and "plates/desk.mp4" in overview,
          f"the ComfyUI graph opens with README notes, one per section, in the order they run: {notes}")
    page.evaluate("document.activeElement.blur()")
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    page.wait_for_function("document.querySelector('#view').dataset.picture === 'shot'", timeout=20000)
    page.keyboard.press("Home")
    page.wait_for_function("document.querySelector('#view').dataset.picture === 'shot'", timeout=20000)
    check(page.get_attribute("#view", "data-picture") == "shot", "paused, on frame 3 and on frame 0, the viewer shows the shot, not the plate")
    made, renders = passes(), page.locator("#log li:has-text('Render v')").count()
    page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    check(passes() == made and page.locator("#log li:has-text('Render v')").count() == renders and "Nothing changed" in page.text_content("#hud"),
          "Enter again with nothing changed runs nothing twice: no Klein pass, no render step")
    seen = len(page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)"))
    page.click("[data-tool=erase]")
    page.fill("#prompt", "")
    stroke([(0.7, 0.3), (0.75, 0.35)])
    page.wait_for_timeout(1500)  # SAM runs while the strokes rest
    page.click("#generate")
    page.wait_for_function(DONE.format(n=2), timeout=120000)
    check(titles() == ["2. Erase", "1. Paint"], f"two edits, numbered from the bottom: {titles()}")
    lines = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")[seen:]
    found = next((i for i, line in enumerate(lines) if "under the stroke" in line), len(lines))
    started = next((i for i, line in enumerate(lines) if line.startswith("Edit 2: Erase")), -1)
    asked = sum("asking Klein's prompt writer" in line for line in lines)
    check(found < started and asked == 1, f"a whole-object erase: SAM runs while the strokes rest, the prompt writer once "
          f"(SAM at line {found}, start at line {started}, {asked} request(s))")

    page.wait_for_function("[...document.querySelectorAll('#log li span')].some((e) => e.textContent.includes('Erase pass, preview took'))", timeout=120000)
    seen = len(page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)"))
    page.click("#history li:last-child .del")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check(titles() == ["1. Erase"], f"after a removal the numbers start from 1 again: {titles()}")
    page.wait_for_function("[...document.querySelectorAll('#log li span')].slice(%d).some((e) => e.textContent.includes('used again'))" % seen,
                           timeout=60000)
    lines = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")[seen:]
    check(not any("Track the erase (about" in line or "Erase pass, preview (about" in line for line in lines),
          "the paint removed, the next render uses the erase's matte and clean plate again: nothing tracks or cleans twice")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=120000)
    lines = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")[seen:]
    stopped = [line for line in lines if re.match(r"^(clean|cleanup|shot|matte|comp|review|export) \S+: cancelled", line)]
    check(not stopped, f"a removal stops no render step: the render it leaves keeps what it made {stopped}")
    behind = [line for line in lines if line.endswith(", in the background")]
    check(bool(behind), f"the render of the edits before the removal goes on in the background: {behind[:2]}")
    steps = [(i, line) for i, line in enumerate(lines) if re.match(r"^Render v\d+: .* \(about \d+ s\)", line)]
    comp = next((i for i, line in steps if "Composite, preview (about" in line and not line.endswith("in the background")), None)
    full = next((i for i, line in steps if ", full size (about" in line or "Export (about" in line), None)
    check(comp is not None and (full is None or comp < full),
          f"the render queue: the preview of the edits on show runs before any full-size step (composite at {comp}, first full size at {full})")
    check(not page.is_disabled("#undo-btn") and page.is_disabled("#redo-btn"), "undo is live, redo is not")
    page.keyboard.press("Control+z")
    page.wait_for_function(DONE.format(n=2), timeout=120000)
    check(titles() == ["2. Erase", "1. Paint"] and not page.is_disabled("#redo-btn"), f"undo brings the removed edit back: {titles()}")
    page.keyboard.press("Control+Shift+z")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check(titles() == ["1. Erase"], f"redo removes it again: {titles()}")
    check(page.is_visible("#editing") and page.text_content("#editing") == "Editing 1 · Erase",
          "undo and redo keep the current edit: the next strokes still change it")
    page.keyboard.press("Escape")

    page.click("#history li .what")
    check(page.text_content("#editing") == "Editing 1 · Erase" and page.is_checked("#whole"), "selecting shows the editing tag and the edit's switches")
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
    log = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    check(any("another try" in line for line in log), "Ctrl+Enter tries another seed on the selected edit")
    page.keyboard.press("Escape")
    made = passes()
    for _ in range(3):
        page.keyboard.press("Control+z")
        page.wait_for_timeout(300)
    page.wait_for_function("!document.querySelector('#history li.busy')", timeout=180000)
    check(titles() == ["2. Erase", "1. Paint"] and words() == ["Whole object", "a red fire"],
          f"three undos go back through the seed, the words and the removal: {titles()} {words()}")
    check(passes() == made, f"undo gets the kept results back: no Klein pass runs again ({passes() - made} ran)")
    page.select_option("#preview-size", index=1)
    check("928 × 512" in page.text_content("#status"), "the preview size menu sets the shot size")
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
    check(label.startswith("E +1.0") and len(titles()) == 2 and (up[0] > red[0] + 8 or red[0] > 240),
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
    # The colour picker: I opens the browser's own eyedropper (a stand-in here), which picks anywhere on the screen
    color = page.input_value("#color")
    page.evaluate("""() => { window.__drops = 0;
      window.EyeDropper = class { open() { window.__drops++; return Promise.resolve({ sRGBHex: "#2E7D32" }); } }; }""")
    page.keyboard.press("i")
    page.wait_for_function("document.querySelector('#color').value === '#2e7d32'", timeout=5000)
    check(page.evaluate("window.__drops") == 1, "I opens the browser's eyedropper and the brush takes its colour")
    # Without an eyedropper (Firefox, Safari), I arms the in-frame picker: a click gives the brush the colour on show there
    page.evaluate("() => { window.__ED = window.EyeDropper; delete window.EyeDropper; }")
    page.keyboard.press("i")
    check(page.evaluate("document.querySelector('#view').classList.contains('picking')"), "without an eyedropper, I arms the in-frame picker")
    want = pixel(0.9, 0.1)
    page.mouse.click(box["x"] + box["w"] * 0.9, box["y"] + box["h"] * 0.1)
    got = page.input_value("#color")
    rgb = [int(got[i:i + 2], 16) for i in (1, 3, 5)]
    check(all(abs(p - q) <= 6 for p, q in zip(rgb, want)) and not page.evaluate("document.querySelector('#view').classList.contains('picking')"),
          f"a click on the frame picks the colour on show there: {got} against the frame's {[round(v) for v in want]}")
    page.evaluate("() => { window.EyeDropper = window.__ED; }")
    page.fill("#color", color)
    page.wait_for_timeout(2500)
    log = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    for key in ("posted as", "prompt writer", "Klein quick pass", "ComfyUI started it"):
        check(any(key in line for line in log), f"the log says what happens under the hood: {key}")

    # One edit at a time: new words and more strokes change the current edit; New edit and another tool start a new one
    page.keyboard.press("b")
    page.fill("#prompt", "a dog"); page.evaluate("document.activeElement.blur()")
    stroke([(0.2, 0.7), (0.25, 0.75)])
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=3), timeout=120000)
    check(titles()[0] == "3. Paint" and page.is_visible("#editing") and page.text_content("#editing") == "Editing 3 · Paint"
          and page.input_value("#prompt") == "a dog", "the edit just made stays current, its words in the prompt")
    page.locator(".promptbar").screenshot(path=os.path.join(SHOTS, "5_promptbar.png"))
    page.fill("#prompt", "a cat"); page.evaluate("document.activeElement.blur()")
    stroke([(0.26, 0.7), (0.3, 0.74)])
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#history li small')?.textContent === 'a cat' && !document.querySelector('#history li.busy')",
                           timeout=120000)
    check(len(titles()) == 3 and words()[0] == "a cat", f"new words and more strokes change the same edit: {titles()} {words()}")
    page.keyboard.press("n")
    check(page.is_hidden("#editing") and page.input_value("#prompt") == "" and page.is_disabled("#new-edit"), "N, New edit, closes the current edit")
    page.fill("#prompt", "a bird"); page.evaluate("document.activeElement.blur()")
    stroke([(0.6, 0.7), (0.65, 0.72)])
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=4), timeout=120000)
    check(titles()[:2] == ["4. Paint", "3. Paint"] and words()[:2] == ["a bird", "a cat"], f"after New edit the strokes make edit 4: {titles()} {words()}")
    page.keyboard.press("l")
    check(page.is_hidden("#editing") and page.input_value("#prompt") == "", "another tool closes the current edit")
    stroke([(0.1, 0.1), (0.2, 0.12)])
    page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(n=5), timeout=120000)
    check(titles()[0] == "5. Light" and words()[1] == "a bird", f"the light is a new edit: {titles()} {words()}")
    page.click("#new-edit")
    check(page.is_hidden("#editing") and page.is_disabled("#new-edit"), "the New edit button closes it too")
    page.click("#history li .what")
    page.mouse.click(cx, cy, button="right")
    page.hover("#ctx > li:has(> span:first-child:text-is('Edit'))")
    page.click("#ctx .sub button:has-text('New edit')")
    check(page.is_hidden("#editing") and len(titles()) == 5, "New edit in the right-click menu closes the selected edit")
    page.screenshot(path=os.path.join(SHOTS, "2_end.png"))
    errors = [e for e in errors if "favicon" not in e]
    check(not errors, f"no console errors: {errors}")


WATCH = """() => { window.__lines = []; if (window.__watch) window.__watch.disconnect();
  window.__watch = new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) =>
    (n.querySelectorAll ? [...n.querySelectorAll('span')] : [n]).forEach((s) => window.__lines.push(s.textContent)))));
  window.__watch.observe(document.querySelector('#log'), { childList: true, subtree: true }); }"""  # lines added from now on


def added(page, steps):  # how many jobs of each step were taken from the job index, and how many were posted, since WATCH
    lines = page.evaluate("window.__lines")
    return {f"{s}: {w}": sum(1 for line in lines if line.startswith(f"{s}: {w}")) for s in steps for w in ("made before", "posted")}


REVIEWED = "Composite, full size took"  # a render's full-size composite in the log: "Render v2: Composite, full size took 3.1 s"


def open_path(page, path):
    """Open plate, ComfyUI files: a path typed into the dialog, then Open."""
    page.click("#open-btn"); page.click("#open [data-tab=files]"); page.fill("#path", path); page.click("#open-go")


def save_scene(page):
    """Save scene keeps it on this ComfyUI: the newest scene, read back through the scenes route."""
    page.click("#save-btn")
    page.wait_for_function("/saved on this ComfyUI/.test(document.querySelector('#status').textContent)", timeout=20000)
    base = page.url.split("/extensions/")[0]
    name = json.loads(urllib.request.urlopen(f"{base}/paintaplate/scenes").read())[0]["name"]
    return name, json.loads(urllib.request.urlopen(f"{base}/paintaplate/scenes/{name}").read())


def open_scene(page, name):
    """Open plate, Scenes: the scene by its name, then Open."""
    page.click("#open-btn"); page.click("#open [data-tab=scenes]")
    page.wait_for_selector("#scenes .scene", timeout=10000)
    page.evaluate("(n) => [...document.querySelectorAll('#scenes .scene')].find((b) => b.querySelector('.name').textContent === n).click()", name)
    page.click("#open-go")


def fluid_flow(page):
    """A blank plate: keyframes on the LTX grid, copied, pasted, dragged, deleted and undone; then its shot, the first edit."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input")
    note = page.text_content("#b-note")
    check(note.startswith("512 × 320, 33 frames at 24 fps"), f"the blank plate form says what it will make: {note}")
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    check(not page.is_hidden("#fluid") and page.is_disabled("[data-tool=erase]") and page.is_disabled("[data-tool=light]"),
          "a blank plate opens as a fluid shot: its panel shows, Erase and Light wait for a plate")
    box = page.eval_on_selector("#view", "e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }")

    def stroke(pts):
        page.mouse.move(box["x"] + pts[0][0] * box["w"], box["y"] + pts[0][1] * box["h"])
        page.mouse.down()
        for x, y in pts[1:]:
            page.mouse.move(box["x"] + x * box["w"], box["y"] + y * box["h"], steps=5)
        page.mouse.up()

    def keys():
        return page.eval_on_selector_all("#tl-keys .tl-kf", "els => els.map(e => +e.dataset.frame).sort((a, b) => a - b)")

    page.fill("#prompt", "thick white smoke")
    page.evaluate("document.activeElement.blur()")
    stroke([(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End")
    stroke([(0.45, 0.3), (0.55, 0.2)])
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
    log = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    sent = [line for line in log if line.startswith("Fluid v1: 3 keyframe")]
    check(sent and 'prompt "ainvfxfluid, thick white smoke"' in sent[0] and "at 1, 18, 33," in sent[0],
          f"Enter generates with the trigger, the words and the three keyframes: {sent}")
    rows = page.eval_on_selector_all("#history li .title", "els => els.map(e => e.textContent)")
    check(rows == ["1. Fluid"] and any("under the edits: the fluid shot v1" in line for line in log) and not page.is_disabled("[data-tool=erase]"),
          f"the fluid shot is the first edit and the plate under the next ones, with Erase and Light on: {rows}")
    page.click('#history li[data-id="fluid"] .edit')
    check(not page.is_hidden("#fluid"), "the pencil on the fluid row brings its keyframes back")
    page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    log = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    check(not any(line.startswith("Fluid v2") for line in log) and "already made" in page.text_content("#hud"),
          "Enter again on the same keyframes and words makes nothing twice")
    page.screenshot(path=os.path.join(SHOTS, "4_fluid.png"))
    page.keyboard.press("e")
    check(page.is_hidden("#fluid") and page.eval_on_selector_all("#history li .title", "els => els.map(e => e.textContent)") == ["1. Fluid"],
          "another tool closes the keyframes: the fluid shot stays the first edit")
    page.click('#history li[data-id="fluid"] .eye')
    page.wait_for_function("[...document.querySelectorAll('#log li span')].some((e) => e.textContent.includes('under the edits: the blank plate'))", timeout=60000)
    page.click('#history li[data-id="fluid"] .eye')
    page.wait_for_function("[...document.querySelectorAll('#log li span')].filter((e) => e.textContent.includes('under the edits: the fluid shot v1')).length >= 2", timeout=60000)
    check(page.get_attribute('#history li[data-id="fluid"] .eye', "aria-pressed") == "true",
          "the eye on the fluid row bypasses it (the blank plate under the edits) and turns it back on (its shot)")

    # A paint edit on the fluid shot, then the scene saved and opened again: all of it comes back, from the job index
    box = page.eval_on_selector("#view", "e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }")
    page.keyboard.press("b")
    page.fill("#prompt", "a lantern"); page.evaluate("document.activeElement.blur()")
    stroke([(0.2, 0.25), (0.3, 0.3)])
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
    page.wait_for_function("window.__lines.some((t) => t.startsWith('review: made before') || t.startsWith('review: posted'))", timeout=120000)
    grew = added(page, ("ingest", "fluid", "edit", "shot", "matte", "comp", "review"))
    posted = {k: v for k, v in grew.items() if k.endswith("posted") and v}
    check(not posted and all(grew[f"{s}: made before"] >= 1 for s in ("fluid", "edit", "shot", "review")),
          f"the scene opens again as it was: the fluid shot, the edit and every render step from the job index, nothing run twice: {grew}")
    check(not errors, f"no console errors in the fluid shot: {errors}")


def scene_flow(page):
    """A plate with a paint and a whole-object erase, saved as a scene and opened again: every job from the job index."""
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps')", timeout=60000)
    page.wait_for_function("/Describe the edit|Ready to play/.test(document.querySelector('#status').textContent)", timeout=60000)
    box = page.eval_on_selector("#view", "e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }")

    def stroke(pts):
        page.mouse.move(box["x"] + pts[0][0] * box["w"], box["y"] + pts[0][1] * box["h"])
        page.mouse.down()
        for x, y in pts[1:]:
            page.mouse.move(box["x"] + x * box["w"], box["y"] + y * box["h"], steps=5)
        page.mouse.up()

    def settled(limit=180):  # Generate says Generate again for three seconds running: no edit, no render step left
        calm, t0 = 0, time.time()
        while calm < 3 and time.time() - t0 < limit:
            page.wait_for_timeout(1000)
            calm = calm + 1 if page.text_content("#generate").strip() == "Generate" else 0

    def reviews(n):  # the full-size composite of the edits on show, the last step Generate starts
        page.wait_for_function(f"window.__lines.filter((t) => t.includes('{REVIEWED}')).length >= {n}", timeout=180000)

    page.evaluate(WATCH)
    page.keyboard.press("b")
    page.fill("#prompt", "a red fire"); page.evaluate("document.activeElement.blur()")
    stroke([(0.3, 0.6), (0.35, 0.65)])
    page.keyboard.press("Enter")
    page.wait_for_function("""(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      return t.join() === '1. Paint' && !document.querySelector('#history li.busy'); })()""", timeout=120000)
    reviews(1)  # each set of edits renders to its export before the next edit, so the scene's every step is made once
    page.keyboard.press("e")
    page.fill("#prompt", "the cup"); page.evaluate("document.activeElement.blur()")
    stroke([(0.6, 0.4), (0.62, 0.45)])
    page.wait_for_timeout(1500)
    page.keyboard.press("Enter")
    page.wait_for_function("""(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      return t.join() === '2. Erase,1. Paint' && !document.querySelector('#history li.busy'); })()""", timeout=120000)
    reviews(2)
    settled()
    name, _ = save_scene(page)
    page.evaluate(WATCH)
    open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=120000)
    page.wait_for_function("""(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      return t.join() === '2. Erase,1. Paint' && !document.querySelector('#history li.busy'); })()""", timeout=120000)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('review: made before') || t.startsWith('review: posted'))", timeout=180000)
    settled()
    grew = added(page, ("ingest", "prompt", "edit", "clean", "cleanup", "shot", "matte", "comp", "review"))
    posted = {k: v for k, v in grew.items() if k.endswith("posted") and v}
    check(not posted and grew["edit: made before"] >= 2 and grew["review: made before"] >= 1,
          f"a plate's scene opens again from the job index: the edits and every render step, nothing run twice: {grew}")
    check(not errors, f"no page errors in the scene: {errors}")


def menu(page, *labels):
    """Right-click the frame, then go through RV's submenus to the item, as a person would with a mouse."""
    page.click("#view", button="right")
    for label in labels[:-1]:
        page.locator("#ctx li.group > span:first-child", has_text=re.compile(f"^{re.escape(label)}$")).first.hover()
    page.get_by_role("menuitemcheckbox", name=labels[-1], exact=True).click()


def ocio_flow(page):
    """RV's OCIO menu on the right-click: another view, then another File Color Space, at once; the second is made again."""
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
    page.wait_for_timeout(1000)
    pixel = lambda: page.evaluate("(() => { const c = document.querySelector('#view'); return [...c.getContext('2d').getImageData(c.width >> 1, c.height >> 1, 1, 1).data.slice(0, 3)]; })()")  # noqa: E731
    before = pixel()
    page.evaluate(WATCH)
    menu(page, "OCIO", "Displays", "sRGB - Display", "ACES 2.0 - SDR 100 nits (Rec.709)")
    page.wait_for_function("window.__lines.some((t) => t.startsWith('OCIO view: sRGB - Display: ACES 2.0'))", timeout=10000)
    page.wait_for_timeout(500)
    aces = pixel()
    check(aces != before, f"another view applies at once: the same frame through ACES 2.0 SDR, {before} becomes {aces}")
    page.keyboard.press("Space")  # while it plays
    menu(page, "OCIO", "Displays", "sRGB - Display", "Un-tone-mapped")
    page.keyboard.press("Space")
    page.keyboard.press("Home")
    page.wait_for_timeout(700)
    check(max(abs(a - b) for a, b in zip(pixel(), before)) <= 2, "back to Un-tone-mapped while it plays, the frame looks as it did")
    menu(page, "OCIO", "File Color Space", "Utility", "Linear Rec.709 (sRGB)")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('Linear Rec.709 (sRGB)') && document.querySelector('#opening').hidden", timeout=60000)
    page.wait_for_timeout(700)
    lines, linear = page.evaluate("window.__lines"), pixel()
    said = [t for t in lines if t.startswith("File Color Space") or t.startswith("ingest:")]
    check(any(t.startswith("File Color Space: Linear Rec.709 (sRGB)") for t in said) and any(t.startswith("ingest: posted") for t in said) and linear != before,
          f"another File Color Space: the viewer shows it, and the plate opens again in it for the models and the export: {before} becomes {linear}; {said}")
    menu(page, "OCIO", "File Color Space", "Utility", "sRGB Encoded Rec.709 (sRGB)")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('sRGB Encoded Rec.709 (sRGB)') && document.querySelector('#opening').hidden", timeout=60000)
    check(not errors, f"no page errors with OCIO: {errors}")


def race_flow(page):
    """Generate pressed while the render of the edit before it starts, before its first step. On a plate just opened, the
    page's running step was a stale { phase } object, so preempt() threw, and the new edit was listed but never made
    (from 0.4.10; the live CI job of 0.5.7). The mock holds the render's first upload for 4 s, so the press lands there.
    It runs last, on a fresh page, so no other page's upload takes the hold."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    base = page.url.split("/extensions/")[0]
    open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
    page.wait_for_timeout(500)
    passes = lambda: sum("Klein quick pass" in t for t in page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)"))  # noqa: E731

    def edit(words, pts):
        page.fill("#prompt", words)
        page.locator("#prompt").blur()
        box = page.locator("#view").bounding_box()
        page.mouse.move(box["x"] + pts[0][0] * box["width"], box["y"] + pts[0][1] * box["height"])
        page.mouse.down()
        for x, y in pts[1:]:
            page.mouse.move(box["x"] + x * box["width"], box["y"] + y * box["height"], steps=5)
        page.mouse.up()
        page.keyboard.press("Enter")

    made = passes()
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
    page.wait_for_timeout(1000)
    check(not errors, f"Generate while the render before it starts, before its first step: no page error {errors}")
    page.wait_for_function(DONE.format(n=2), timeout=120000)
    page.wait_for_function(f"[...document.querySelectorAll('#log li span')].filter((e) => e.textContent.includes('Klein quick pass')).length >= {made + 2}",
                           timeout=60000)
    check(passes() == made + 2, f"and the new edit is made, as the one before: {passes() - made} Klein passes")


def oom_flow(page):
    """The GPU runs out of memory once (the mock's /mock/oom): the page frees ComfyUI's memory, waits until it is released,
    then runs the fluid shot again. Posted at once, the retry ran before ComfyUI freed anything and ran out again (29 Oct)."""
    base = page.url.split("/extensions/")[0]
    urllib.request.urlopen(urllib.request.Request(f"{base}/mock/oom", json.dumps({"workflow": "fluid", "times": 1}).encode(),
                                                  {"Content-Type": "application/json"}))
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    box = page.eval_on_selector("#view", "e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }")
    page.mouse.move(box["x"] + 0.45 * box["w"], box["y"] + 0.7 * box["h"]); page.mouse.down()
    page.mouse.move(box["x"] + 0.55 * box["w"], box["y"] + 0.6 * box["h"], steps=6); page.mouse.up()
    page.evaluate("document.activeElement.blur()"); page.keyboard.press("Enter")
    page.wait_for_function("""(() => { const r = document.querySelector('#history li[data-id="fluid"]');
      return !!r && !r.classList.contains('busy') && document.querySelector('#fluid').hidden; })()""", timeout=120000)
    ev = json.loads(urllib.request.urlopen(f"{base}/mock/events").read())
    oom, free, posted = [e for e in ev if e[0] == "oom"], [e for e in ev if e[0] == "free"], [e for e in ev if e[0] == "prompt"]
    waited = len(posted) >= 2 and len(free) == 1 and posted[-1][1] >= free[0][1] + 1.0
    check(len(oom) == 1 and waited, f"out of memory once: the page frees ComfyUI's memory, waits until it is released, then makes the shot: "
          f"{[(e[0], round(e[1] - ev[0][1], 2)) for e in ev]}")


def keys_flow(page):
    """Every key the Keys dialog documents does what it says, and every key the menu shows is in the Keys dialog."""
    doc = page.evaluate("[...document.querySelectorAll('#help dt')].map((e) => e.textContent).join(' | ')")  # the keys column
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

    def key(k, test, *, hold=0):
        page.keyboard.press(k)
        page.wait_for_timeout(hold or 60)
        results[k] = bool(test())
    page.keyboard.press("Home"); start = frame()
    key("ArrowRight", lambda: frame() == start + 1); key("ArrowLeft", lambda: frame() == start)
    key("End", lambda: frame() == int(text("#frame-total").strip("/ "))); key("Home", lambda: frame() == start)
    key("Space", lambda: "playing" in attr("#play-btn", "class")); page.keyboard.press("Space")
    key("ArrowDown", lambda: "playing" in attr("#play-btn", "class")); page.keyboard.press("ArrowDown")
    key("]", lambda: "Out point" in text("#hud")); key("[", lambda: "In point" in text("#hud")); key("\\", lambda: "cleared" in text("#hud"))
    key("F6", lambda: attr("#wipe-btn", "aria-pressed") == "true"); page.keyboard.press("F6")
    key("1", lambda: text("#hud") == "1:1"); key("f", lambda: text("#hud") == "Fit")
    key("e", lambda: "on" in attr("[data-tool=erase]", "class")); key("l", lambda: "on" in attr("[data-tool=light]", "class"))
    key("b", lambda: "on" in attr("[data-tool=paint]", "class"))
    size = int(text("#size-out")); key("=", lambda: int(text("#size-out")) > size); key("-", lambda: int(text("#size-out")) == size)
    key("x", lambda: attr("#rub-btn", "aria-pressed") == "true"); page.keyboard.press("x")
    key("i", lambda: page.evaluate("window.__drops") >= 2)  # the eyedropper again: flow() put its stand-in in place
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
    page.keyboard.down("o"); page.wait_for_timeout(60); results["hold O"] = text("#hud") == "Plate"; page.keyboard.up("o")
    key("?", lambda: page.evaluate("document.querySelector('#help').open")); key("?", lambda: not page.evaluate("document.querySelector('#help').open"))
    failed = [k for k, ok in results.items() if not ok]
    check(not failed, f"every documented key does what the Keys dialog says ({len(results)} presses): {failed or 'all'}")


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


def log_lines(page):
    return page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")


def wait_log(page, js, timeout, what):
    """page.wait_for_function; on a timeout, the page's last log lines, its render steps and its status, so a CI log says why."""
    try:
        page.wait_for_function(js, timeout=timeout)
    except Exception:
        print(f"  ... no {what}; the page's last log lines:\n    " + "\n    ".join(log_lines(page)[-30:]), flush=True)
        print("  stages:", page.text_content("#stages"), "| status:", page.text_content("#status"), flush=True)
        raise


def paint_once(page, words, pts):
    box = page.eval_on_selector("#view", "e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }")
    page.fill("#prompt", words); page.evaluate("document.activeElement.blur()")
    page.mouse.move(box["x"] + pts[0][0] * box["w"], box["y"] + pts[0][1] * box["h"]); page.mouse.down()
    for x, y in pts[1:]:
        page.mouse.move(box["x"] + x * box["w"], box["y"] + y * box["h"], steps=5)
    page.mouse.up()




def added_line(text):  # a JS test: a line added to the log since WATCH holds `text` (the log keeps its last 400 lines only)
    return "window.__lines.some((t) => t.includes(%s))" % json.dumps(text)


def hdr_flow(page, port):
    """SDR to HDR is off by default, as its shots flicker (29 Oct): an EXR plate shows no switch, a blank plate no 16-bit.
    With ?hdr=1: no switch for a video plate; on by default for an EXR plate, where it runs after the full-size shot and
    before the full-size composite, with its live preview in a corner naming its step of the pass's steps; switched off,
    the next render leaves it out. Esc stops the render on its way and Enter goes on."""
    open_path(page, "paintaplate/hdr_room")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('EXR') && document.querySelector('#opening').hidden", timeout=60000)
    check(page.is_hidden("#hdr-switch") and page.evaluate("document.querySelector('#b-depth').closest('label').style.display") == "none",
          "SDR to HDR is off by default: no switch for an EXR plate, no 16-bit blank plate")
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?hdr=1")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    page.evaluate(WATCH)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    lines = lambda: page.evaluate("window.__lines")  # noqa: E731
    open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
    check(page.is_hidden("#hdr-switch"), "a video plate stays SDR: no SDR-to-HDR switch")
    open_path(page, "paintaplate/hdr_room")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('EXR') && document.querySelector('#opening').hidden", timeout=60000)
    check(not page.is_hidden("#hdr-switch") and page.is_checked("#hdr-on"), "an EXR plate: SDR to HDR is on by default")
    page.evaluate(WATCH)
    page.keyboard.press("b")
    paint_once(page, "a red lamp", [(0.3, 0.6), (0.36, 0.7)])
    page.keyboard.press("Enter")
    page.wait_for_function("!document.querySelector('#live-inset').hidden", timeout=240000)
    caption = page.text_content("#live-inset figcaption")
    wait_log(page, added_line(REVIEWED), 240000, "full-size composite")
    check(bool(re.search(r"step \d+ of \d+", caption)) and page.is_hidden("#live-inset"),
          f"a full-size pass shows its live preview in a corner while the preview plays, then it goes: {caption}")
    new = lines()
    at = lambda text: next((i for i, line in enumerate(new) if text in line), None)  # noqa: E731
    check(at("SDR to HDR took") is not None and at("SDR to HDR took") < at(REVIEWED),
          "the full-size shot goes through SDR to HDR before the full-size composite the viewer plays")
    page.evaluate(WATCH)
    page.click("#hdr-on")
    wait_log(page, added_line(REVIEWED), 240000, "full-size composite without SDR to HDR")
    check(not any("SDR to HDR took" in line for line in lines()) and not page.is_checked("#hdr-on"),
          "switched off, the next render ends with the SDR shot: no SDR-to-HDR step")
    page.click("#hdr-on")
    page.evaluate("document.activeElement.blur()")  # the switch keeps the focus, and a focused input takes the keys
    page.evaluate(WATCH)
    page.keyboard.press("Control+Enter")  # another seed: a new edit pass, then a new render
    wait_log(page, "window.__lines.some((t) => /^Render v\\d+: .* \\(about \\d+ s\\)/.test(t))", 120000, "render step")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    if not any(line.startswith("Stopped (Esc)") for line in lines()):  # Ctrl+Enter selected the edit: Esc deselects first
        check("Esc again stops generating" in page.text_content("#hud"), "with an edit selected, Esc deselects first and says a second Esc stops generating")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    check(any(line.startswith("Stopped (Esc)") for line in lines()) and not page.is_disabled("#generate"),
          "Esc stops the render step on its way, and Generate can go on")
    page.evaluate(WATCH)
    page.keyboard.press("Enter")
    wait_log(page, added_line(REVIEWED), 240000, "full-size composite after Enter")
    check(True, "Enter goes on from where it stopped: the full-size composite is made")
    check(not errors, f"no console errors with SDR to HDR: {errors}")


def fluid16_flow(page):
    """A blank plate asked in 16-bit: its fluid shot goes through SDR to HDR and opens as an EXR plate, the switch on."""
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
    page.wait_for_function("!document.querySelector('#hdr-switch').hidden", timeout=60000)
    new = page.evaluate("window.__lines")
    check(any("16-bit" in line for line in new) and any("SDR to HDR took" in line for line in new),
          "16-bit: the fluid shot goes through SDR to HDR")
    check(page.is_checked("#hdr-on"), "the HDR fluid shot is an EXR plate: SDR to HDR is on for the edits on it")
    check(not errors, f"no console errors in a 16-bit fluid shot: {errors}")


def drag(page, selector, dx, dy):
    box = page.locator(selector).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + dx, y + dy, steps=5); page.mouse.up()


def layout_flow(page, port):
    """The side panel and the log resize from their dividers, keep the stage usable, keep their sizes for the next session,
    and take their first size back on a double-click."""
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


def phone(browser, port):
    """The page on a phone, upright and on its side: the frame, the transport, the menu and the log fit the screen."""
    for name, size in (("upright", {"width": 390, "height": 844}), ("sideways", {"width": 844, "height": 390})):
        page = browser.new_page(viewport=size, is_mobile=True, has_touch=True, device_scale_factor=3)
        page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html")
        page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=20000)
        page.click("#open-btn"); page.fill("#path", "plates/desk.mp4"); page.click("#open-go")
        page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
        page.wait_for_timeout(500)
        logged = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--root", default="/tmp/paintaplate_mock_ui")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    shutil.rmtree(a.root, ignore_errors=True)
    os.makedirs(SHOTS, exist_ok=True)
    mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_comfy.py"), "--plate", "--port", str(a.port), "--root", a.root],
                            stdout=open(os.path.join(SHOTS, "mock.log"), "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{a.port}/system_stats", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("the mock ComfyUI did not start")
        items = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{a.port}/paintaplate/browse?path=plates").read())["items"]
        check([i["path"] for i in items] == ["plates/desk.mp4"], "the browse route lists the mock's plate")
        import numpy as np, OpenEXR  # an EXR with values above white, outside input/plates, for the frame route
        hdr = os.path.join(a.root, "input", "paintaplate", "hdr_test")
        os.makedirs(hdr, exist_ok=True)
        img = np.zeros((32, 64, 3), np.float16)
        img[:, :32], img[:, 32:] = 4.0, 0.5
        for n in (1001, 1002):
            OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}, {"RGB": img}).write(os.path.join(hdr, f"f.{n}.exr"))
        make_hdr_plate(a.root)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL") or None)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            flow(page, a.port)
            fluid_flow(page)
            scene_flow(page)
            ocio_flow(page)
            keys_flow(page)
            oom_flow(page)
            hdr_flow(page, a.port)
            fluid16_flow(page)
            layout_flow(page, a.port)
            phone(browser, a.port)
            page.close()  # its renders ask for nothing more: the next upload the mock holds is the race page's own
            race = browser.new_page(viewport={"width": 1400, "height": 900})
            race.goto(f"http://127.0.0.1:{a.port}/extensions/ainvfx-paintaplate/paintaplate.html")
            race.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
            race_flow(race)
            browser.close()
    finally:
        mock.terminate()
    print("UI MOCK PASSED")


if __name__ == "__main__":
    main()
