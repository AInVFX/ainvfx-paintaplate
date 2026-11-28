"""The colour picker on a fluid shot's keyframes. With the keyframes open, a click of the pipette on a painted keyframe
takes that keyframe's colour, on the last frame and on the first frame alike: the keyframe is the picture there, and the
blank plate under it is black."""

OPEN = "document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')"
PICKING = "document.querySelector('#pick').getAttribute('aria-pressed') === 'true'"
ON_KEY = "document.querySelector(\"#tl-keys .tl-kf[data-frame='{f}']\")?.classList.contains('on') === true"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320")
    page.select_option("#b-fps", "24"); page.fill("#b-frames", "33"); page.dispatch_event("#b-frames", "input")
    page.click("#open-go")
    page.wait_for_function(OPEN, timeout=60000)
    swatches = page.eval_on_selector_all(".swatches .sw[data-color]", "(s) => s.map((b) => b.dataset.color)")
    bright = [c for c in swatches if sum(int(c[i:i + 2], 16) for i in (1, 3, 5)) > 240]
    U.check(len(bright) >= 2, f"two swatches bright enough to tell from the black plate: {swatches}")
    first, last = bright[0], bright[1]

    def pick(x, y):  # the pipette on, then a click on the frame at (x, y), from 0 to 1 across it
        page.click("#pick")
        U.check(U.until(page, PICKING, 5000), "the pipette is on")
        box = U.view_box(page)
        page.mouse.click(box["x"] + x * box["w"], box["y"] + y * box["h"])
        U.check(U.until(page, "!(" + PICKING + ")", 5000), "a click on the frame ends the pipette")
        return page.input_value("#color")

    page.click(f".sw[data-color='{first}']")
    U.stroke(page, [(0.4, 0.7), (0.5, 0.7), (0.6, 0.7)])
    U.check(U.until(page, ON_KEY.format(f=0), 5000), "a keyframe on the first frame")
    page.keyboard.press("End")
    U.check(U.until(page, "document.querySelector('#tl-keys .tl-kf.on') === null", 5000), "the playhead on the last frame")
    page.click(f".sw[data-color='{last}']")
    U.stroke(page, [(0.4, 0.3), (0.5, 0.3), (0.6, 0.3)])
    U.check(U.until(page, ON_KEY.format(f=32), 5000), "a keyframe on the last frame")
    got = pick(0.5, 0.3)
    U.check(got == last, f"on the last frame, the pick takes its keyframe's colour {last}: {got}")
    page.keyboard.press("Home")
    U.check(U.until(page, ON_KEY.format(f=0), 5000), "the playhead back on the first frame")
    got = pick(0.5, 0.7)
    U.check(got == first, f"on the first frame, the pick takes its keyframe's colour {first}, not the black plate's: {got}")
    U.no_errors(errors, "while picking on the keyframes")
    page.close()
