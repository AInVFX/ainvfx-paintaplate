"""Full screen does the work. There, the right-click menu and the keys reach what an edit needs: Colours… (S) shows the
swatches, the picker and the pipette in a dialog over the frame, and Text prompt… (T) the edit's text prompt, which Enter applies.
Ctrl+O opens a plate and Ctrl+S saves the scene, both taken from the browser. With the wipe on, comma steps its left side
and period its right side through the plate, the first frame and the finished Render steps. The File menu has no ComfyUI
graph: the Export dialog writes it."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
ALONE = "document.body.classList.contains('plate-alone')"
MENU = "[...document.querySelectorAll('#ctx button')].map((b) => b.textContent.trim())"
PREVENTED = """() => { window.__prevented = []; addEventListener('keydown', (e) => { if (e.ctrlKey) window.__prevented.push([e.key, e.defaultPrevented]); }); }"""
SIDES = "[document.querySelector('#wipe .label.left').textContent, document.querySelector('#wipe .label.right').textContent]"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.keyboard.press("`")
    page.wait_for_function(ALONE, timeout=5000)
    v = page.locator("#view").bounding_box()
    page.mouse.click(v["x"] + v["width"] / 2, v["y"] + v["height"] / 2, button="right")
    items = page.evaluate(MENU)
    has = lambda label, key: any(t.startswith(label) and t.endswith(key) for t in items)  # noqa: E731
    U.check(has("Colours…", "S") and has("Text prompt…", "T") and has("Open plate…", "Ctrl+O") and has("Save scene", "Ctrl+S"),
            "full screen: the right-click menu has Colours… (S), Text prompt… (T), Open plate… (Ctrl+O) and Save scene (Ctrl+S)")
    U.check(not any(t.startswith("ComfyUI graph") for t in items), "the File menu has no ComfyUI graph: the Export dialog writes it")
    page.keyboard.press("Escape")

    page.keyboard.press("s")
    U.check(page.is_visible("#colours") and page.is_visible("#colours .swatches #pick") and page.is_visible("#colours #color"),
            "S shows the swatches, the pipette and the picker in a dialog over the frame")
    U.check(page.evaluate("document.activeElement === document.body") and page.evaluate("document.querySelector('#colours .swatches').nextElementSibling.tagName") == "MENU",
            "the dialog takes no focus, so Space and Enter stay the page's keys, and its Close button comes after the swatches")
    page.click('#colours .sw[data-color="#d32f2f"]')
    U.check(page.get_attribute('.sw[data-color="#d32f2f"]', "aria-pressed") == "true", "a swatch in the dialog sets the colour")
    page.keyboard.press("s")
    U.check(U.poll(page, lambda: page.is_hidden("#colours") and page.evaluate("!!document.querySelector('.tools .swatches')")),
            "S again closes it, and the swatches go back to the panel, in the dialog's close event")

    page.keyboard.press("t")
    U.check(page.is_visible("#words"), "T shows the edit's text prompt in a dialog")
    page.fill("#words-field", "a brass lantern")
    page.keyboard.press("Enter")
    U.check(page.is_hidden("#words") and page.input_value("#prompt") == "a brass lantern", f"Enter applies the text prompt: {page.input_value('#prompt')!r}")

    page.evaluate(PREVENTED)
    page.keyboard.press("Control+o")
    U.check(page.is_visible("#open"), "Ctrl+O opens a plate")
    page.keyboard.press("Escape")
    page.keyboard.press("Control+s")
    U.check(U.poll(page, lambda: "scene" in page.text_content("#status").lower(), 10), f"Ctrl+S saves the scene: {page.text_content('#status')!r}")
    got = page.evaluate("window.__prevented")
    U.check(["o", True] in got and ["s", True] in got, f"the page takes Ctrl+O and Ctrl+S from the browser: {got}")

    page.keyboard.press("p")
    U.stroke(page, [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=180000)
    page.keyboard.press("F6")
    first = page.evaluate(SIDES)
    page.keyboard.press(",")
    one = page.evaluate(SIDES)
    page.keyboard.press(",")
    two = page.evaluate(SIDES)
    U.check(first[0] == "Plate" and one[0] == "Edited first frame" and two[0] not in ("Plate", "Edited first frame") and two[1] == first[1],
            f"comma steps the wipe's left side: {first[0]}, {one[0]}, {two[0]}, against {first[1]}")
    page.keyboard.press(".")
    three = page.evaluate(SIDES)
    U.check(three[1] not in (first[1], three[0]) and three[0] == two[0], f"period steps the right side, never to the pass on the left: {three}")
    seen = []
    for _ in range(16):
        page.keyboard.press(",")
        seen.append(page.evaluate(SIDES)[0])
        if seen[-1] == "Plate":
            break
    U.check(seen[-1] == "Plate" and three[1] not in seen, f"the left side comes back to the plate, passing over the pass on the right: {seen}")
    page.keyboard.press("`")
    U.no_errors(errors, "with the menu, the dialogs and the keys of full screen")
    page.close()
