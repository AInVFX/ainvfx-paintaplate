"""Finish > Upscale over a fluid shot: « Plate, upscaled » upscales the fluid shot, which is the plate under the edits, so
« Composite, upscaled » keeps the smoke where the matte is black. A small Paint over a bright fluid shot on a 512 x 320
blank plate, upscaled to 1024 x 640: the upscaled plate and the upscaled composite both read as the fluid shot, far from the
black of the blank plate. The mock writes each upscaled frame flat in its source frame's mean colour, so a mean level of the
viewer's picture compares them."""

MEAN = """(() => { const c = document.querySelector('#view'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let s = 0, n = 0; for (let i = 0; i < d.length; i += 4 * 97) { s += d[i] + d[i + 1] + d[i + 2]; n += 3; } return s / n / 255; })()"""
SHOWN = "document.querySelector('#stages li.shown .name')?.textContent ?? ''"
SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"


def level(page):  # the viewer's mean level from 0 to 1, once two reads a quarter of a second apart agree
    last = None
    for _ in range(40):
        page.wait_for_timeout(250)
        now = round(page.evaluate(MEAN), 3)
        if now == last:
            return now
        last = now
    return last


def shows(page, U, label, click=True):  # a step on display, by its row
    if click:
        page.click(f"#stages li.pick:has-text('{label}')")
    U.check(U.until(page, f"{SHOWN} === {label!r}", 10000), f"« {label} » on display: {page.evaluate(SHOWN)!r}")
    return level(page)


def run(browser, port, U):
    page = U.load(browser, port)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.click('.sw[data-color="#ffffff"]')  # a bright fluid shot: white strokes over most of the frame
    U.paint_once(page, "thick white smoke", [(x, 0.1 + 0.1 * i) for i in range(9) for x in ((0.05, 0.95) if i % 2 == 0 else (0.95, 0.05))])
    page.evaluate(U.WATCH); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Fluid shot, full size: done in"), 240000, "the fluid shot")
    page.click(".tools [data-tool=paint]"); page.click('.sw[data-color="#d32f2f"]')
    page.fill("#prompt", "a red ball"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.45, 0.45), (0.55, 0.55)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the Paint's full-size composite")
    page.click("#finish-btn"); page.click("#finish-upscale")
    page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", "1024"); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
    U.poll(page, lambda: "1024 x 640" in page.evaluate(SIZE), 3)
    page.keyboard.press("Escape")
    U.wait_log(page, U.added_line("Composite, upscaled: done in"), 240000, "Upscale's steps over the fluid shot")
    comp = shows(page, U, "Composite, upscaled", click=False)
    plate = shows(page, U, "Plate, upscaled")
    fluid = shows(page, U, "Fluid shot, full size")
    U.check(fluid > 0.2, f"the fluid shot is bright, so black and smoke are far apart: {fluid}")
    U.check(abs(plate - fluid) < 0.1, f"« Plate, upscaled » is the fluid shot upscaled, not the black blank plate: {plate} against {fluid}")
    U.check(abs(comp - fluid) < 0.1, f"« Composite, upscaled » keeps the smoke where the matte is black: {comp} against {fluid}")
    page.close()
