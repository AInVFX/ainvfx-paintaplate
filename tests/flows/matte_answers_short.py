"""On a 16 GB GPU with RAM short for the next job's frames, the free between the matte and the review movie clears
ComfyUI's cache, as every free did before (matte_answers: the same GPU with room keeps it)."""

CARD = {"vram": 17.2e9, "ram": 65.5e9, "ram_free": 4e9}  # a 16 GB GPU, and 4 GB of RAM free: short for the frames of the review movie


def frees(page, port, U, seen_lines, seen_events):  # each « Memory freed before … » line with the free_memory the page posted
    lines = [t for t in U.log_lines(page)[seen_lines:] if t.startswith("Memory freed before")]
    events = [e for e in U.mock_route(port, "/mock/events") if e[0] == "free"][seen_events:]
    return [(line.split(":")[0].removeprefix("Memory freed before "), e[2]) for line, e in zip(lines, events)], len(lines), len(events)


def run(browser, port, U):
    U.mock_route(port, "/mock/card", CARD)
    page = U.load(browser, port)
    U.open_plate(page)
    page.fill("#prompt", "a red fire"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.3, 0.5), (0.4, 0.52), (0.5, 0.5)])
    lines0, events0 = len(U.log_lines(page)), sum(e[0] == "free" for e in U.mock_route(port, "/mock/events"))
    page.click("#generate")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.wait_log(page, "document.querySelector('#render-left').textContent === 'full size ready'", 180000, "full-size composite")
    U.settled(page)
    made, n_lines, n_events = frees(page, port, U, lines0, events0)
    U.check(n_lines == n_events and dict(made).get("the review movie") is True,
            f"with RAM short for the frames, the free before the review movie clears ComfyUI's cache: {made}")
    page.close()
