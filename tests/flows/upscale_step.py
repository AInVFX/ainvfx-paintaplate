"""Finish > Upscale's steps are steps of the render, as SDR to HDR's is. Its switch changes the Render panel at once: on, with a
Paint, « Plate, upscaled », « Layer, upscaled » and « Composite, upscaled » follow the full-size composite and run with the render,
with no Export, and « full size ready » waits for them; off, their rows go; on again, they come back made, with no new job.
Export then posts no Upscale job, and the zip holds the upscaled set. It upscales at the plate's own size, 1280 x 704, which the mock
holds in the sandbox's memory (upscale_size checks the sizes)."""
import zipfile

ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
UP = ["Plate, upscaled", "Layer, upscaled", "Composite, upscaled"]


def run(browser, port, U):
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 52 * 2 ** 30})
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    ups = lambda: [r for r in rows() if r[0] in UP]  # noqa: E731
    names = lambda: [r[0] for r in rows()]  # noqa: E731
    made = lambda: len(ups()) == 3 and all("done" in r[2].split() for r in ups())  # noqa: E731
    jobs = lambda start: [t for t in U.log_lines(page)[start:] if t.startswith("Upscale: ") or "upscaled: about" in t]  # noqa: E731

    def planned():  # the three rows, after the full-size composite, none waiting for Export
        n = names()
        return [r[0] for r in ups()] == UP and "Composite, full size" in n and n.index(UP[0]) > n.index("Composite, full size") and all("later" not in r[2].split() for r in ups())

    def switch(on):  # a person's path: the menu, the switch, the menu closed
        if not page.is_visible("#finish-upscale"):
            page.click("#finish-btn")
        if page.is_checked("#finish-upscale") != on:
            page.click("#finish-upscale")
        page.click("#finish-btn")
        if page.is_visible("#finish-upscale"):
            page.keyboard.press("Escape")

    page.click("#finish-btn"); page.click("#finish-upscale")  # the size asked for stays with the plate while the switch is off
    own = page.evaluate("() => [...document.querySelectorAll('#finish-upscale-size option')].findIndex((o) => o.textContent.startsWith('1280 x 704'))")
    page.select_option("#finish-upscale-size", index=own); page.click("#finish-upscale"); page.click("#finish-btn")
    U.check(own >= 0 and not page.is_checked("#finish-upscale"), f"the plate's own size is chosen, with the switch off: option {own}")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    page.wait_for_function("!!document.querySelector('#stages li.now')", timeout=120000)
    switch(True)
    U.poll(page, planned, 1.5)
    U.check(planned(), f"while a render runs, Upscale on adds its three steps after the full-size composite, at once: {rows()}")
    switch(False)
    U.poll(page, lambda: not ups(), 1.5)
    U.check(not ups(), f"Upscale off removes its rows at once: {rows()}")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite")
    U.poll(page, lambda: page.text_content("#render-left") == "full size ready", 3)
    U.check(not ups() and page.text_content("#render-left") == "full size ready", f"with Upscale off, the render ends at the composite: {rows()}")
    switch(True)
    U.poll(page, planned, 1.5)
    U.check(planned() and page.text_content("#render-left") != "full size ready", f"once the render is made, Upscale on adds its steps at once, and the render is no longer ready: {rows()}")
    U.wait_log(page, U.added_line("Composite, upscaled: done in"), 240000, "Upscale's steps, with no Export")
    U.poll(page, lambda: made() and page.text_content("#render-left") == "full size ready", 3)
    U.check(made() and page.text_content("#render-left") == "full size ready", f"the three steps are made, then « full size ready »: {rows()}")
    switch(False)
    U.poll(page, lambda: not ups(), 1.5)
    U.check(not ups(), f"Upscale off removes the made rows at once: {rows()}")
    start = len(U.log_lines(page))
    switch(True)
    U.poll(page, made, 1.5)
    page.wait_for_timeout(U.QUIET_MS)
    U.check(made() and not jobs(start), f"Upscale on again takes its results back, with no new job: {rows()}, {jobs(start)}")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=280000) as dl:
        page.click("#x-go")
    parts = {n.split("/")[1] for n in zipfile.ZipFile(dl.value.path()).namelist() if n.startswith("upscaled/")}
    U.check(parts == {"export", "plate", "layer", "matte"} and not jobs(start), f"Export writes the steps' upscaled set with no Upscale job: {sorted(parts)}, {jobs(start)}")
    page.close()
