"""A step that a new edit's Generate stops while it uploads its images posts no job after the stop. A fluid shot on a blank
plate with the preview off makes its full size first, and that step uploads its keyframe before it posts its job: the mock
holds that upload (/mock/slow). A Paint edit generated then stops the step at 0%. Once the upload ends, the stopped step
posts nothing: the render starts the step again, and its job is the only fluid job. The Paint edit, painted over the
fluid shot, waits for its first frame and is made after it."""
import re

JOB = re.compile(r"^fluid [0-9a-f]{8}: done in ")
STOP = "Fluid shot, full size: stopped at 0% for the new edit."
START = "Fluid shot, full size: about "


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    lines = lambda: page.evaluate("window.__lines")  # noqa: E731
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.select_option("#preview-size", "off")  # the fluid shot's first step is its full size
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.3, 0.7), (0.4, 0.6), (0.5, 0.7)])
    U.mock_route(port, "/mock/slow", {"seconds": 120, "times": 1})  # the next upload is the full size's keyframe: it waits for /mock/release
    page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: any(e[0] == "slow upload" for e in U.mock_route(port, "/mock/events")), 30) and not any(JOB.match(t) for t in lines()),
            "the full size waits for the upload of its keyframe, which the mock holds: no fluid job yet")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=30000)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.4, 0.5), (0.45, 0.52), (0.5, 0.5)])
    page.keyboard.press("Enter")  # Generate: the full size stops for the new edit
    U.wait_log(page, U.added_line(STOP), 10000, "line of the stop for the new edit")
    U.mock_route(port, "/mock/release", {})
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)
    after = lines()[next(i for i, t in enumerate(lines()) if STOP in t):]
    job = next((i for i, t in enumerate(after) if JOB.match(t)), None)
    again = next((i for i, t in enumerate(after) if START in t), None)
    U.check(job is not None and again is not None and again < job,
            f"stopped during its upload, the step posts no job: the render starts it again, then its job runs ({[t for t in after if 'Fluid shot' in t or JOB.match(t)]})")
    U.check(sum(bool(JOB.match(t)) for t in lines()) == 1 and sum("Fluid shot, full size: done in" in t for t in lines()) == 1,
            "the fluid shot's full size is made once, by its one job")
    U.check(U.row_titles(page) == ["2. Paint", "1. Fluid"] and any(re.match(r"^Edit 2: done", t) for t in lines()),
            f"the Paint edit waits for the fluid shot's first frame, then is made: {U.row_titles(page)}")
    U.no_errors(errors, "after the stop and the steps that followed")
    page.close()
