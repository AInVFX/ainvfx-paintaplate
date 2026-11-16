"""The check of how the Help closes (tests/flows/README.md). A click outside the Help closes it, as Esc
does. A click inside its box, and a drag that starts inside and ends outside, keep it open."""


def run(browser, port, U):
    page = U.load(browser, port)
    shown = lambda: page.evaluate("document.querySelector('#help').open")  # noqa: E731
    page.click("#help-btn")
    U.check(shown(), "the Help button opens the Help")
    box = page.locator("#help").bounding_box()
    page.mouse.click(box["x"] + 4, box["y"] + 4)
    U.check(shown(), "a click inside the Help's box, on its edge, keeps it open")
    page.mouse.move(box["x"] + 4, box["y"] + 4); page.mouse.down(); page.mouse.move(4, 4); page.mouse.up()
    U.check(shown(), "a drag that starts inside the Help and ends outside keeps it open")
    page.mouse.click(4, 4)
    U.check(not shown(), "a click outside the Help closes it")
    page.click("#help-btn"); page.keyboard.press("Escape")
    U.check(not shown(), "Esc closes it too")
    page.close()
