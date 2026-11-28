"""The check of full screen (tests/flows/README.md). The key ` shows the plate alone, fitted: no panel, menu bar,
timeline or status line. The right-click menu and the keys keep working there, and a new frame's number shows for a
moment in the HUD's corner. Esc or ` comes back to the zoom the page had before."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
AROUND = (".top", ".tools", ".side", ".log", ".promptbar", ".transport", "#timeline", "#status")
ZOOM = "document.querySelector('#view').style.transform"
ALONE = "document.body.classList.contains('plate-alone')"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.keyboard.press("2")
    before = page.evaluate(ZOOM)
    page.keyboard.press("`")
    page.wait_for_function(ALONE, timeout=5000); page.wait_for_timeout(300)
    shown = [s for s in AROUND if page.is_visible(s)]
    U.check(shown == [], f"full screen: no panel, menu bar, timeline or status line shows: {shown}")
    iw, ih = page.evaluate("[innerWidth, innerHeight]")
    box, v = page.locator("#viewport").bounding_box(), page.locator("#view").bounding_box()
    U.check(box["width"] >= iw - 1 and box["height"] >= ih - 1, f"the viewer fills the screen: {box} on {iw} x {ih}")
    cx, cy = v["x"] + v["width"] / 2, v["y"] + v["height"] / 2
    U.check(abs(cx - iw / 2) < 2 and abs(cy - ih / 2) < 2 and (abs(v["width"] - (iw - 24)) < 2 or abs(v["height"] - (ih - 24)) < 2),
            f"the plate is fitted, in the middle: {v} on {iw} x {ih}")
    page.mouse.click(cx, cy, button="right")
    U.check(page.is_visible("#ctx"), "the right-click menu opens in full screen")
    page.keyboard.press("Escape")
    U.check(page.is_hidden("#ctx") and page.evaluate(ALONE), "Esc closes the menu first, and the plate stays alone")
    start = int(page.text_content("#frame-now"))  # the plate's own number: from 1 for a movie
    page.keyboard.press("ArrowRight")
    U.check(U.poll(page, lambda: page.text_content("#frame-now") == str(start + 1), 5) and page.text_content("#hud") == str(start + 1),
            f"the keys keep working: the right arrow steps from frame {start}, and the new number shows in the corner: {page.text_content('#hud')!r}")
    hb = page.evaluate("(() => { const r = document.querySelector('#hud').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()")
    U.check(hb[0] > iw / 2 and hb[1] > ih / 2 and hb[2] > iw - 40 and hb[3] > ih - 40, f"the frame number sits in the bottom-right corner: {hb} on {iw} x {ih}")
    U.check(U.poll(page, lambda: "on" not in page.get_attribute("#hud", "class").split(), 4), "the number shows for a moment, then goes")
    page.keyboard.press("`")
    U.check(not page.evaluate(ALONE) and all(page.is_visible(s) for s in (".top", ".tools", ".side", ".log", ".transport")),
            "` again: the panels, the menu bar, the timeline and the status line are back")
    U.check(U.poll(page, lambda: page.evaluate(ZOOM) == before, 5), f"and the zoom is the one it left: {page.evaluate(ZOOM)} for {before}")
    page.keyboard.press("`"); page.wait_for_function(ALONE, timeout=5000); page.keyboard.press("Escape")
    U.check(not page.evaluate(ALONE) and U.poll(page, lambda: page.evaluate(ZOOM) == before, 5), "Esc comes back the same way")
    page.keyboard.press("ArrowRight")
    U.check(U.poll(page, lambda: page.text_content("#frame-now") == str(start + 2), 5) and page.text_content("#hud") != str(start + 2),
            "out of full screen, a new frame's number stays in the transport alone")
    page.close()
