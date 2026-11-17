"""The check of how the Help closes (tests/flows/README.md). A click outside the Help closes it, as Esc
does. A click inside its box, and a drag that starts inside and ends outside, keep it open."""


ROOM = 800  # px of content at most at 1400 x 900, where the Help can take 866: a browser whose fonts run 8% taller still shows a tab whole


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
    page.set_viewport_size({"width": 1400, "height": 900})
    page.click("#help-btn")
    tabs = page.evaluate("[...document.querySelectorAll('#help [role=tab]')].map((b) => b.textContent)")
    U.check(tabs == ["Getting started", "Tools", "Viewer", "Colour", "Render and export", "Keys", "Models and licences"], f"the Help's seven tabs, in order: {tabs}")
    over = []
    for name in tabs:
        page.click(f"#help [role=tab]:text-is('{name}')"); page.wait_for_timeout(150)
        size = page.evaluate("(() => { const d = document.querySelector('#help'), r = d.getBoundingClientRect(); return [r.top, r.bottom, d.scrollHeight, d.clientHeight]; })()")
        if size[0] < 0 or size[1] > 900 or size[2] > size[3] + 1 or size[2] > ROOM: over.append(f"{name} {size}")
    U.check(not over, f"each tab fits one screen at 1400 x 900, with no scroll, in at most {ROOM} px: {over or 'all seven'}")
    rule = "The plate's colour space comes from its file: change it only for a camera's log footage."
    U.check(rule in page.text_content('#help .help-tab[data-help="colour"]'), "the Colour tab says where the plate's colour space comes from, and when to change it")
    page.keyboard.press("Escape")
    page.close()
