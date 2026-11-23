"""Finish > Upscale's steps are steps of the render, as SDR to HDR's is. Its switch changes the Render panel at once: on, with a
Paint, « Plate, upscaled », « Layer, upscaled » and « Composite, upscaled » follow the full-size composite and run with the render,
with no Export, and « full size ready » waits for them; off, their rows go; on again, they come back made, with no new job.
Export then posts no Upscale job, and the zip holds the upscaled set. The player shows each made step as any step: the upscaled
composite as the latest result, the canvas at its own size, 1600 x 880, a size above the plate's 1280 x 704 that the mock holds
in the sandbox's memory (upscale_size checks the sizes)."""
import zipfile

ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
UP = ["Plate, upscaled", "Layer, upscaled", "Composite, upscaled"]
SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"
CANVAS = "() => { const c = document.querySelector('canvas[data-picture]'); return [c.width, c.height]; }"


def run(browser, port, U):
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 52 * 2 ** 30})
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    ups = lambda: [r for r in rows() if r[0] in UP]  # noqa: E731
    names = lambda: [r[0] for r in rows()]  # noqa: E731
    made = lambda: len(ups()) == 3 and all("done" in r[2].split() for r in ups())  # noqa: E731
    shown = lambda: [r[0] for r in rows() if "shown" in r[2].split()]  # noqa: E731
    canvas = lambda: page.evaluate(CANVAS)  # noqa: E731
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

    switch(True)  # the size asked for stays with the plate while the switch is off
    page.click("#finish-btn")
    page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", "1600"); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
    U.poll(page, lambda: "1600 x 880" in page.evaluate(SIZE), 3)
    switch(False)
    U.check("1600 x 880" in page.evaluate(SIZE) and not page.is_checked("#finish-upscale"), f"a size of 1600 x 880 is chosen, with the switch off: {page.evaluate(SIZE)!r}")
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
    U.poll(page, lambda: shown() == ["Composite, upscaled"] and canvas() == [1600, 880], 3)
    U.check(shown() == ["Composite, upscaled"] and canvas() == [1600, 880] and page.text_content("#status").startswith("Composite, upscaled: ready, in the viewer."),
            f"the player shows the upscaled composite at its own size: {shown()}, canvas {canvas()}, {page.text_content('#status')!r}")
    view = lambda: page.eval_on_selector("canvas[data-picture]", "e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")  # noqa: E731
    page.keyboard.press("x")  # the X-ray on the upscaled composite, the latest result
    U.poll(page, lambda: page.is_visible("#xray"), 3)
    latest, over = page.text_content("#hud") or "", page.eval_on_selector("#xray", "e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
    page.click("#stages li.pick[data-pass=upcomp]"); page.wait_for_timeout(300)  # pinned, the same step
    page.keyboard.press("x"); page.keyboard.press("x")  # off, then on: its hud names the mattes it reads
    pinned = page.text_content("#hud") or ""
    U.check(page.is_visible("#xray") and over == view() and latest == pinned and latest.startswith("X-ray"),
            f"the X-ray lies over the upscaled composite and reads its full-size mattes, shown as the latest result or pinned: {latest!r} / {pinned!r}, {over} / {view()}")
    page.keyboard.press("x"); page.click("#stages li.pick[data-pass=upcomp]")  # X-ray off; the latest result again
    U.poll(page, lambda: shown() == ["Composite, upscaled"], 3)
    page.keyboard.press("F5")  # the Colour Inspector, Shift+click on the frame's centre
    v = view(); page.keyboard.down("Shift"); page.mouse.click(v[0] + v[2] / 2, v[1] + v[3] / 2); page.keyboard.up("Shift")
    U.poll(page, lambda: bool(page.get_attribute("#inspector", "data-value")), 5)
    src, value, px = (page.get_attribute("#inspector", k) for k in ("data-source", "data-value", "data-pixel"))
    x, y = (int(n) for n in (px or "-9,-9").split(","))
    U.check(src == "Composite, upscaled" and bool(value) and abs(x - 640) <= 1 and abs(y - 352) <= 1,
            f"the Colour Inspector reads the upscaled composite, at the plate's pixel under the pointer: {src!r}, {value!r}, {px!r}")
    page.keyboard.press("F5")
    page.click("#stages li.pick[data-pass=review]")
    U.poll(page, lambda: shown() == ["Composite, full size"] and canvas() == [1280, 704], 3)
    U.check(shown() == ["Composite, full size"] and canvas() == [1280, 704], f"a click on the full-size composite displays it at the plate's size: {shown()}, canvas {canvas()}")
    page.click("#stages li.pick[data-pass=upplate]")
    U.poll(page, lambda: shown() == ["Plate, upscaled"] and canvas() == [1600, 880], 3)
    U.check(shown() == ["Plate, upscaled"] and canvas() == [1600, 880], f"a click on an upscaled step displays it at its own size: {shown()}, canvas {canvas()}")
    page.click("#stages li.pick[data-pass=upplate]")
    U.poll(page, lambda: shown() == ["Composite, upscaled"] and canvas() == [1600, 880], 3)
    U.check(shown() == ["Composite, upscaled"] and canvas() == [1600, 880], f"a second click displays the latest result again: {shown()}, canvas {canvas()}")
    switch(False)
    U.poll(page, lambda: not ups() and shown() == ["Composite, full size"] and canvas() == [1280, 704], 3)
    U.check(not ups() and shown() == ["Composite, full size"] and canvas() == [1280, 704], f"Upscale off removes the made rows at once, and the player shows the composite: {rows()}, canvas {canvas()}")
    start = len(U.log_lines(page))
    switch(True)
    U.poll(page, lambda: made() and shown() == ["Composite, upscaled"], 3)
    page.wait_for_timeout(U.QUIET_MS)
    U.check(made() and shown() == ["Composite, upscaled"] and canvas() == [1600, 880] and not jobs(start),
            f"Upscale on again takes its results back with no new job, and the player shows the upscaled composite: {rows()}, canvas {canvas()}, {jobs(start)}")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=280000) as dl:
        page.click("#x-go")
    parts = {n.split("/")[1] for n in zipfile.ZipFile(dl.value.path()).namelist() if n.startswith("upscaled/")}
    taken = [t for t in U.log_lines(page)[start:] if t.startswith("export: taken from the job index")]
    U.check(parts == {"export", "plate", "layer", "matte"} and not jobs(start) and len(taken) == 1,
            f"Export takes its job from the job index and writes the steps' upscaled set, with no Upscale job: {sorted(parts)}, {jobs(start)}, {taken}")
    page.close()
