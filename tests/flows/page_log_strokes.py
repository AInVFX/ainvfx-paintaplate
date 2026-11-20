"""The log while painting says each fact once: strokes that follow one another quickly replace the prompt writer's request
each time, with no line for a request replaced before its answer, and one request line for the caption that arrives."""
import re


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    page.fill("#prompt", "a red ball"); page.evaluate("document.activeElement.blur()")
    U.mock_route(port, "/mock/hold", {"output": "text", "seconds": 1.5, "times": 4})  # each request lasts long enough for the next stroke to replace it
    page.evaluate(U.WATCH)
    for k in range(4):
        U.stroke(page, [(0.3 + 0.05 * k, 0.5), (0.33 + 0.05 * k, 0.52)])
    U.wait_log(page, U.added_line("asking Klein's prompt writer"), 30000, "the caption's request")
    page.wait_for_timeout(2000)
    lines = page.evaluate("window.__lines")
    asked = [t for t in lines if t.startswith("Edit 1: asking Klein's prompt writer")]
    stopped = [t for t in lines if re.match(r"prompt \w+: stopped", t)]
    U.check(len(asked) == 1, f"one request line, for the caption that arrives: {len(asked)} lines")
    U.check(not stopped, f"no line for a request the next stroke replaced: {stopped}")
    page.keyboard.press("Escape")
    U.no_errors(errors, "while painting")
    page.close()
