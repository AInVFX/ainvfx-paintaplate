"""The prefetch stops when a plate opens: the prompt writer's request for the last plate's strokes ends with the plate, and
no caption for them arrives on the new one."""
import re


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    page.fill("#prompt", "a red ball"); page.evaluate("document.activeElement.blur()")
    U.mock_route(port, "/mock/hold", {"output": "text", "seconds": 5, "times": 1})  # the prefetch's request lasts 5 s
    U.stroke(page, [(0.3, 0.5), (0.36, 0.52)])
    page.wait_for_timeout(500)
    page.evaluate(U.WATCH)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    if U.until(page, "document.querySelector('#ask').open", 3000):
        page.click("#ask-yes")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.wait_for_timeout(6000)  # past the request's 5 s
    lines = page.evaluate("window.__lines")
    stopped = [t for t in lines if re.match(r"prompt \w+: stopped", t)]
    done = [t for t in lines if re.match(r"prompt \w+: done", t) or t.startswith("Edit 1: asking Klein's prompt writer")]
    U.check(stopped and not done, f"the request stops with the plate, and no caption arrives on the new one: stopped {stopped}, after {done}")
    U.no_errors(errors, "after the new plate")
    page.close()
