"""Strokes that follow one another replace the prompt writer's request each time, with no line for a request the next
stroke replaced. The mock holds each request open, and each stroke starts once ComfyUI runs the last one's request, so
the replacement always meets a request that ComfyUI has."""
import re


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    page.fill("#prompt", "a red ball"); page.evaluate("document.activeElement.blur()")
    U.mock_route(port, "/mock/hold", {"output": "text", "seconds": 4, "times": 3})  # each request still runs when the next stroke starts (the mock reads an interrupt between steps)
    page.evaluate(U.WATCH)
    held = lambda: sum(e[0] == "held" for e in U.mock_route(port, "/mock/events"))
    for k in range(3):
        U.stroke(page, [(0.3 + 0.05 * k, 0.5), (0.33 + 0.05 * k, 0.52)])
        U.check(U.poll(page, lambda: held() == k + 1, 15), f"the request for stroke {k + 1} runs in ComfyUI ({held()})")
    U.stroke(page, [(0.5, 0.5), (0.53, 0.52)])  # the fourth stroke replaces the third's request, which ComfyUI runs
    U.wait_log(page, U.added_line("asking Klein's prompt writer"), 30000, "the caption's request")
    lines = page.evaluate("window.__lines")
    stopped = [t for t in lines if re.match(r"prompt \w+: stopped", t)]
    U.check(not stopped, f"no line for a request the next stroke replaced: {stopped}")
    page.keyboard.press("Escape")
    U.no_errors(errors, "while painting")
    page.close()
