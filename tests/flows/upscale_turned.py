"""Finish > Upscale turned off, or set to another size, while one of its steps runs. The step stops at once, as for a new edit, and
its finished jobs stay in the job index. Off: nothing more runs, and no upscaled step is made. On again: the steps run. Another
size inside a step: that size's own steps run from the first, to « full size ready », with no error. Back at the first size, the
step it had made is still made, and the others run. The sizes, 1600 x 880 and 1400 x 770, are above the plate's 1280 x 704 and
fit the mock in a small machine's memory."""

ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
UP = ["Plate, upscaled", "Layer, upscaled", "Composite, upscaled"]
CANVAS = "() => { const c = document.querySelector('canvas[data-picture]'); return [c.width, c.height]; }"
RESTS = "document.querySelector('#render-left').textContent === 'full size ready' || document.querySelector('#status').textContent.startsWith('Error')"


def run(browser, port, U):
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 52 * 2 ** 30})
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    ups = lambda: [r for r in rows() if r[0] in UP]  # noqa: E731
    made = lambda: len(ups()) == 3 and all("done" in r[2].split() for r in ups())  # noqa: E731
    canvas = lambda: page.evaluate(CANVAS)  # noqa: E731
    lines = lambda start: U.log_lines(page)[start:]  # noqa: E731
    status = lambda: page.text_content("#status") or ""  # noqa: E731
    bad = lambda start: [t for t in lines(start) if t.startswith("Error") or ": failed after" in t]  # noqa: E731
    stopped = lambda start: [t for t in lines(start) if ": stopped after" in t]  # noqa: E731

    def menu(shown):  # the Finish menu, opened or closed by its button
        if page.is_visible("#finish-upscale") != shown:
            page.click("#finish-btn")

    def switch(on):
        menu(True)
        if page.is_checked("#finish-upscale") != on:
            page.click("#finish-upscale")
        menu(False)

    def size(px):  # typed in Custom…
        menu(True)
        page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
        page.fill("#ask-field", px); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
        menu(False)

    switch(True); size("1600")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Plate, upscaled: about"), 240000, "the first of Upscale's steps")
    start = len(lines(0))
    switch(False)
    U.poll(page, lambda: page.is_hidden("#stop") and bool(stopped(start)), 5)
    page.wait_for_timeout(U.QUIET_MS)
    U.check(not ups() and page.is_hidden("#stop") and stopped(start) and not any("upscaled: done in" in t for t in lines(start)) and not bad(start),
            f"Upscale off inside « Plate, upscaled » stops the step at once, and nothing more runs: {rows()}, {lines(start)}")
    start = len(lines(0))
    switch(True)
    page.wait_for_function("(n) => [...document.querySelectorAll('#log li')].slice(n).some((e) => e.textContent.includes('Layer, upscaled: about'))", arg=start, timeout=120000)
    U.check(any("Plate, upscaled: done in" in t for t in lines(start)) and not bad(start), f"on again, the steps run: {ups()}, {bad(start)}")
    start = len(lines(0))
    size("1400")
    U.poll(page, lambda: bool(stopped(start)), 5)
    U.check(stopped(start) and not any("Layer, upscaled: done in" in t for t in lines(start)), f"another size inside « Layer, upscaled » stops the step at once: {lines(start)}")
    page.wait_for_function(RESTS, timeout=200000)
    U.poll(page, lambda: made() and canvas() == [1400, 770], 3)
    U.check(made() and canvas() == [1400, 770] and status().startswith("Composite, upscaled: ready, in the viewer.") and not bad(start),
            f"the steps of the size asked for run from the first, with no error: {ups()}, canvas {canvas()}, {status()!r}, {bad(start)}")
    start = len(lines(0))
    size("1600")
    U.poll(page, lambda: [r[0] for r in ups() if "done" in r[2].split()][:1] == ["Plate, upscaled"], 3)
    kept = [r[0] for r in ups() if "done" in r[2].split()]
    page.wait_for_function(RESTS, timeout=200000)
    U.poll(page, lambda: made() and canvas() == [1600, 880], 3)
    U.check(kept[:1] == ["Plate, upscaled"] and made() and canvas() == [1600, 880] and not any("Plate, upscaled: about" in t for t in lines(start)) and not bad(start),
            f"back at the first size, the step it had made is still made, and the others run: {kept}, {ups()}, canvas {canvas()}, {bad(start)}")
    page.close()
