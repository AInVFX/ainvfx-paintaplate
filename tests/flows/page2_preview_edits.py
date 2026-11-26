"""A new preview size while a render of edits makes its full size: the step at work stops, at any progress, the preview at
the new size runs, then the full size runs again from its start. The mock holds the full-size shot open, so the change
always meets it."""

LOG = "[...document.querySelectorAll('#log li')].map((e) => e.textContent)"
ROWS = "[...document.querySelectorAll('#stages li .name')].map((e) => e.textContent)"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    said = lambda part: [line for line in page.evaluate(LOG) if part in line]
    rows = lambda: page.evaluate(ROWS)

    page.select_option("#preview-size", "off")
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.4, 0.5), (0.45, 0.52), (0.5, 0.5)])
    U.mock_route(port, "/mock/hold", {"slot": "hero", "seconds": 8, "times": 1})  # with no preview pass, the first shot job is the full size
    page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: any(e[0] == "held" for e in U.mock_route(port, "/mock/events")), 90), "the full-size shot runs, held open")
    page.select_option("#preview-size", "2")
    U.check(U.poll(page, lambda: bool(said("Shot, full size: stopped at")), 5), "half size while the full-size shot runs: it stops")
    U.settled(page)
    stop, r = said("Shot, full size: stopped at")[0], rows()
    U.check(stop.endswith("for the half-size preview. It runs again after the preview.") and "Shot, preview" in r and "Shot, full size" in r
            and r.index("Shot, preview") < r.index("Shot, full size") and len(said("Shot, full size: done in")) == 1,
            f"the half-size preview runs first, then the full size once to its end: « {stop} », rows {r}")
    U.no_errors(errors, "after the change of preview size")
    page.close()
