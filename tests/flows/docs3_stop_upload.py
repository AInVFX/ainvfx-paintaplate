"""A new edit's Generate stops the render step at work, whatever the step, and a step stopped while it uploads its images
posts no job after the stop. A fluid shot on a blank plate uploads its keyframe before its first step posts its job: the
mock holds that upload (/mock/slow). A Paint edit generated then stops the step at 0%: the full size with the preview off,
the preview with a preview size. Once the upload ends, the stopped step posts nothing: the render starts the step again,
and each step's job runs once. The Paint edit, painted over the fluid shot, waits for its first frame and is made after it."""
import re

JOB = re.compile(r"^fluid [0-9a-f]{8}: done in ")


def scene(browser, port, U, preview, step, jobs, held):
    """One blank plate with the Preview menu at `preview`: `step` is the fluid shot's first step, the render makes `jobs`
    fluid jobs in all, and the mock has held `held` uploads once this one waits."""
    errors = []
    page = U.load(browser, port, errors=errors)
    lines = lambda: page.evaluate("window.__lines")  # noqa: E731
    stop, start = f"{step}: stopped at 0% for the new edit.", f"{step}: about "
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.select_option("#preview-size", preview)
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.3, 0.7), (0.4, 0.6), (0.5, 0.7)])
    U.mock_route(port, "/mock/slow", {"seconds": 120, "times": 1})  # the next upload is the first step's keyframe: it waits for /mock/release
    page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: sum(e[0] == "slow upload" for e in U.mock_route(port, "/mock/events")) == held, 30) and not any(JOB.match(t) for t in lines()),
            f"{step} waits for the upload of its keyframe, which the mock holds: no fluid job yet")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=30000)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.4, 0.5), (0.45, 0.52), (0.5, 0.5)])
    page.keyboard.press("Enter")  # Generate: the step at work stops for the new edit
    U.wait_log(page, U.added_line(stop), 10000, f"line of the stop for the new edit, {step}")
    U.check(not any("finishing before" in t for t in lines()), f"{step}: no step finishes before the new edit")
    U.mock_route(port, "/mock/release", {})
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)
    after = lines()[next(i for i, t in enumerate(lines()) if stop in t):]
    job = next((i for i, t in enumerate(after) if JOB.match(t)), None)
    again = next((i for i, t in enumerate(after) if start in t), None)
    U.check(job is not None and again is not None and again < job,
            f"stopped during its upload, the step posts no job: the render starts it again, then its job runs ({[t for t in after if 'Fluid shot' in t or JOB.match(t)]})")
    U.check(sum(bool(JOB.match(t)) for t in lines()) == jobs and sum(f"{step}: done in" in t for t in lines()) == 1,
            f"{step} is made once, and the fluid shot by {jobs} job{'' if jobs == 1 else 's'} in all")
    U.check(U.row_titles(page) == ["2. Paint", "1. Fluid"] and any(re.match(r"^Edit 2: done", t) for t in lines()),
            f"the Paint edit waits for the fluid shot's first frame, then is made: {U.row_titles(page)}")
    U.no_errors(errors, f"after the stop of {step} and the steps that followed")
    page.close()


def run(browser, port, U):
    scene(browser, port, U, "off", "Fluid shot, full size", 1, 1)  # the preview off: the fluid shot's first step is its full size
    scene(browser, port, U, "2", "Fluid shot, preview", 2, 2)  # a half-size preview: the first step is the preview, a step that Generate stops too
