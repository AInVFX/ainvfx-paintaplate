"""A new preview size while the fluid shot's steps run: the step at work stops, at any progress, the preview at the new
size runs, then the full size runs again from its start. The mock holds each window open, so the change always meets it:
the step's upload of its keyframes, its job at work, the preview at the old size. Latent preview, which makes no preview
pass, stops nothing."""

FLUID = '#history li[data-id="fluid"]'
LOG = "[...document.querySelectorAll('#log li')].map((e) => e.textContent)"
ROWS = "[...document.querySelectorAll('#stages li .name')].map((e) => e.textContent)"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    said = lambda part: [line for line in page.evaluate(LOG) if part in line]
    rows = lambda: page.evaluate(ROWS)

    def until(part, n, seconds, what):  # the n-th line of the log that holds `part`
        U.check(U.poll(page, lambda: len(said(part)) >= n, seconds), f"{what} ({len(said(part))} of {n})")

    def event(what, n):  # the mock's n-th event `what`: an upload held open, a job held open
        U.check(U.poll(page, lambda: sum(e[0] == what for e in U.mock_route(port, "/mock/events")) >= n, 30), f"the mock: {what} ({n})")

    def before(a, b):  # the Render panel lists the steps in the order they ended
        r = rows()
        return a in r and b in r and r.index(a) < r.index(b), r

    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)

    # 1. Preview off: the fluid shot's first step is its full size. Half size while it uploads its keyframe, held open:
    #    the step stops there and posts no job, the preview runs, then the full size
    page.select_option("#preview-size", "off")
    U.paint_once(page, "thick white smoke", [(0.3, 0.7), (0.4, 0.6), (0.5, 0.7)])
    U.mock_route(port, "/mock/slow", {"seconds": 120, "times": 1})
    page.keyboard.press("Enter")
    event("slow upload", 1)
    page.select_option("#preview-size", "2")
    until("Fluid shot, full size: stopped at", 1, 5, "half size while the full size uploads its keyframe: the full size stops")
    U.mock_route(port, "/mock/release", {})
    U.settled(page)
    stop = said("Fluid shot, full size: stopped at")[0]
    ok, r = before("Fluid shot, preview", "Fluid shot, full size")
    U.check(stop.endswith("for the half-size preview. It runs again after the preview.") and ok and len(said("Fluid shot, full size: done in")) == 1,
            f"stopped during its upload, the full size posts no job: the preview runs first, then the full size once (« {stop} », rows {r})")

    # 2. Preview off, a new version: its full size runs, held open. Half size: it stops, the preview runs, then the full size
    page.select_option("#preview-size", "off")
    U.settled(page)
    page.click(f"{FLUID} .edit")
    U.stroke(page, [(0.55, 0.3), (0.6, 0.35), (0.65, 0.3)])
    U.mock_route(port, "/mock/hold", {"output": "plate", "seconds": 8, "times": 1})
    page.keyboard.press("Enter")
    event("held", 1)
    page.select_option("#preview-size", "2")
    until("Fluid shot, full size: stopped at", 2, 5, "half size while the full size runs: it stops")
    U.settled(page)
    ok, r = before("Fluid shot, preview", "Fluid shot, full size")
    U.check(ok and len(said("Fluid shot, full size: done in")) == 2, f"the half-size preview runs first, then the full size once to its end: rows {r}")

    # 3. Latent preview while a new version's full size runs, held open: nothing stops
    page.select_option("#preview-size", "off")
    U.settled(page)
    page.click(f"{FLUID} .edit")
    U.stroke(page, [(0.6, 0.3), (0.65, 0.35), (0.7, 0.3)])
    U.mock_route(port, "/mock/hold", {"output": "plate", "seconds": 6, "times": 1})
    page.keyboard.press("Enter")
    event("held", 2)
    page.select_option("#preview-size", "latent")
    U.settled(page)
    U.check(len(said("stopped at")) == 2 and len(said("Fluid shot, full size: done in")) == 3,
            f"latent preview while the full size runs: nothing stops, the full size ends ({said('stopped at')})")

    # 4. Half size, then quarter size while a new version's half-size preview runs, held open: the preview stops
    #    immediately, the quarter-size preview runs, then the full size
    page.select_option("#preview-size", "2")
    U.settled(page)
    page.click(f"{FLUID} .edit")
    U.stroke(page, [(0.2, 0.3), (0.25, 0.35), (0.3, 0.3)])
    U.mock_route(port, "/mock/hold", {"slot": "width", "seconds": 8, "times": 1})  # the preview: the one fluid job with a width
    page.keyboard.press("Enter")
    event("held", 3)
    page.select_option("#preview-size", "4")
    until("Fluid shot, preview: stopped at", 1, 5, "quarter size while the half-size preview runs: it stops")
    U.settled(page)
    stop = said("Fluid shot, preview: stopped at")[0]
    ok, r = before("Fluid shot, preview", "Fluid shot, full size")
    U.check(stop.endswith("for the quarter-size preview.") and ok, f"the quarter-size preview runs, then the full size: « {stop} », rows {r}")
    U.no_errors(errors, "after the changes of preview size")
    page.close()
