"""On a 16 GB GPU the page frees ComfyUI's memory between families of models (tests/flows/README.md). Between the matte and
the frames steps it keeps ComfyUI's cache, so SAM 3.1's answers survive the composite and a change of matte strategy runs
Follow Matte alone; every other free clears the cache, as before (logic.keepsAnswers), and so does a free when RAM is short
for the next job's frames."""

CARD = {"vram": 17.2e9, "ram": 65.5e9}  # a 16 GB GPU with 61 GB of RAM: the small profile, which frees between families


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
    flags = dict(made)
    U.check(n_lines == n_events and flags.get("the shot") is True and flags.get("the matte") is True and flags.get("the review movie") is False,
            f"Generate on a 16 GB GPU: the frees before the shot and the matte clear ComfyUI's cache, the one before the review movie keeps it: {made}")
    lines1, events1 = len(U.log_lines(page)), sum(e[0] == "free" for e in U.mock_route(port, "/mock/events"))
    page.select_option("#history li label.matte select", "Whole shot")
    U.wait_log(page, "document.querySelector('#render-left').textContent === 'full size ready'", 180000, "full-size composite again")
    U.settled(page)
    changed, n_lines, n_events = frees(page, port, U, lines1, events1)
    U.check(n_lines == n_events and changed and all(flag is False for _, flag in changed),
            f"a change of strategy: every free keeps ComfyUI's cache, so SAM's answers serve again: {changed}")
    page.close()

