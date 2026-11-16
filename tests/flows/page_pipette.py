"""The check of the pipette (tests/flows/README.md). While the pipette is on, it alone is lit: no swatch
is. Its cursor on the frame is an eyedropper whose tip is the cursor's hotspot, so the tip is the pixel a click reads; a
browser that cannot draw the image shows a crosshair. A click on the frame takes the colour there: the pipette goes off,
and the brush has that colour. A swatch clicked while the pipette is on takes over the same way."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
LIT = "[...document.querySelectorAll('.swatches .sw[data-color][aria-pressed=true], .swatches .custom.on')].map((b) => b.dataset.color || 'custom')"
CURSOR = "getComputedStyle(document.querySelector('#view')).cursor"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    pick = lambda: page.get_attribute("#pick", "aria-pressed") == "true"  # noqa: E731
    first, second = page.eval_on_selector_all(".swatches .sw[data-color]", "(s) => s.map((b) => b.dataset.color)")[:2]
    page.click(f".sw[data-color='{first}']")
    U.check(page.evaluate(LIT) == [first] and not pick(), f"a swatch clicked: it alone is lit: {page.evaluate(LIT)}")
    page.click("#pick")
    U.check(pick() and page.evaluate(LIT) == [], f"the pipette on: it is lit, and no swatch is: {page.evaluate(LIT)}")
    cur = page.evaluate(CURSOR)
    U.check(cur.startswith('url("data:image/svg+xml') and cur.endswith(" 2 21, crosshair"),
            f"on the frame, the cursor is the eyedropper with its tip on the hotspot (2, 21), else a crosshair: {cur[-48:]!r}")
    box = page.locator("#view").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.6)
    got = page.input_value("#color")
    U.check(not pick() and got != first and page.evaluate(LIT) in ([got], ["custom"]) and page.evaluate(CURSOR) == "none",
            f"a click on the frame: the pipette goes off, the brush takes the colour there ({got}), and the brush's cursor is back")
    page.click("#pick")
    page.click(f".sw[data-color='{second}']")
    U.check(not pick() and page.evaluate(LIT) == [second] and page.input_value("#color") == second,
            f"a swatch clicked while the pipette is on: the pipette goes off and that swatch is the brush's: {page.evaluate(LIT)}")
    page.close()
