"""The page's behaviour in headless Chromium against tests/mock_comfy.py: no ComfyUI, no GPU, about two minutes.

    python tests/ui_mock.py [--port 8199] [--keep]

Opens a plate from the plate browser, paints two edits, removes one, undoes and redoes, selects an edit and retypes its
words, tries another seed with Ctrl+Enter, undoes three steps, changes the preview size, uses the viewer's colour and the
right-click menu, and checks the log. Then one edit at a time: new words and more strokes change the edit just made, and
New edit (the N key, the button, the menu) or another tool starts a new one. Then a fluid shot: a blank plate, keyframes painted, copied, pasted, dragged,
deleted and brought back, generated, and opened as the plate. Prints UI MOCK PASSED at the end; tests/test_ui_mock.py
runs it. Screenshots go to /tmp/paintaplate_ui_mock.
"""
import argparse, json, os, shutil, subprocess, sys, time, urllib.request

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

    page.click("#open-btn")
    page.wait_for_selector("#plates .plate", timeout=10000)
    names = page.eval_on_selector_all("#plates .plate .plate-name", "els => els.map(e => e.textContent)")
    check("desk.mp4" in names, f"the plate browser lists input/plates: {names}")
    page.click("#plates .plate:has-text('desk.mp4')")
    check(page.input_value("#path") == "plates/desk.mp4", "one click fills the path")
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
    page.wait_for_function("document.querySelector('#render-left').textContent === 'export ready'", timeout=120000)
    lines = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    full = [i for i, line in enumerate(lines) if "plays the full-size shot" in line]
    done = [i for i, line in enumerate(lines) if line.startswith("Export v")]
    check(bool(full and done) and full[-1] < done[-1], f"the viewer plays the full-size shot while the export runs, then the export: {full} {done}")
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

    page.click("#history li:last-child .del")
    page.wait_for_function(DONE.format(n=1), timeout=120000)
    check(titles() == ["1. Erase"], f"after a removal the numbers start from 1 again: {titles()}")
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
    page.keyboard.press("Shift+R")
    view_filter = "getComputedStyle(document.querySelector('#view')).filter"
    check("url(" in page.evaluate(view_filter) and page.text_content("#display-state") == "Red", "Shift+R shows the red channel, as RV's r")
    page.keyboard.press("Shift+E")
    page.mouse.down(); page.mouse.move(cx + 100, cy, steps=5); page.mouse.up()
    label = page.text_content("#display-state")
    check(label.startswith("E +1.0") and len(titles()) == 2, f"Shift+E then a 100 px drag adds one stop and paints nothing: {label}")
    page.mouse.click(cx, cy, button="right")
    groups = page.eval_on_selector_all("#ctx > li > span:first-child", "els => els.map(e => e.textContent)")
    check(groups == ["File", "Edit", "Tools", "Control", "Colour", "View", "Help"], f"right-click opens the menu: {groups}")
    page.hover("#ctx > li:has-text('Colour')")
    page.screenshot(path=os.path.join(SHOTS, "3_menu.png"))
    page.click("#ctx .sub button:has-text('Reset colour')")
    check(page.is_hidden("#display-state") and page.evaluate(view_filter) == "none" and page.is_hidden("#ctx"),
          "Reset colour in the menu clears the filter and closes the menu")
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


def fluid_flow(page):
    """A blank plate: keyframes on the LTX grid, copied, pasted, dragged, deleted and undone; then the shot, used as the plate."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.click("#open-btn")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input")
    note = page.text_content("#b-note")
    check(note.startswith("512 × 320, 33 frames at 24 fps"), f"the blank plate form says what it will make: {note}")
    page.click("#blank-go")
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
    page.wait_for_function("/v1 ready/.test(document.querySelector('#fluid-state').textContent)", timeout=120000)
    log = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    sent = [line for line in log if line.startswith("Fluid v1: 3 keyframe")]
    check(sent and 'prompt "ainvfxfluid, thick white smoke"' in sent[0] and "at 1, 18, 33," in sent[0],
          f"Enter generates with the trigger, the words and the three keyframes: {sent}")
    page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    log = page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")
    check(not any(line.startswith("Fluid v2") for line in log) and "already made" in page.text_content("#hud")
          and page.is_disabled("#generate"), "Enter again on the same keyframes and words makes nothing twice")
    page.screenshot(path=os.path.join(SHOTS, "4_fluid.png"))
    page.click("#fluid-use")
    page.wait_for_function("document.querySelector('#fluid').hidden && document.querySelector('#spec').textContent.includes('prores')", timeout=60000)
    check(not page.is_disabled("[data-tool=erase]"), "Use as the plate opens the fluid shot as a plate: Erase and Light are back")
    check(not errors, f"no console errors in the fluid shot: {errors}")


def phone(browser, port):
    """The page on a phone, upright and on its side: the frame, the transport, the menu and the log fit the screen."""
    for name, size in (("upright", {"width": 390, "height": 844}), ("sideways", {"width": 844, "height": 390})):
        page = browser.new_page(viewport=size, is_mobile=True, has_touch=True, device_scale_factor=3)
        page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html")
        page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=20000)
        page.click("#open-btn"); page.fill("#path", "plates/desk.mp4"); page.click("#open-go")
        page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
        page.wait_for_timeout(500)
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
        items = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{a.port}/paintaplate/plates").read())
        check([i["path"] for i in items] == ["plates/desk.mp4"], "the plates route lists the mock's plate")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            flow(page, a.port)
            fluid_flow(page)
            phone(browser, a.port)
            browser.close()
    finally:
        mock.terminate()
    print("UI MOCK PASSED")


if __name__ == "__main__":
    main()
