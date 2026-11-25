"""Finish > Upscale on a plate with no edit and no SDR to HDR: the plate alone's render has one step, « Plate, upscaled », the plate
itself upscaled with no Export, which the player shows at its own size. Off, the plate shows again; on again, the step comes back
made, with no new job. Export posts no Upscale job, and the zip holds the upscaled plate under upscaled/. It asks for 1600 x 880, a
size above the plate's 1280 x 704 that the mock holds in a small machine's memory."""
import zipfile
import zip_rows  # noqa: E402

ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"
CANVAS = "() => { const c = document.querySelector('canvas[data-picture]'); return [c.width, c.height]; }"


def custom(page, U, px):  # Finish > Upscale's size, typed in Custom…, with the menu open
    page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", px); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
    U.poll(page, lambda: f"{px} x " in page.evaluate(SIZE), 3)


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    names = lambda: [r[0] for r in rows()]  # noqa: E731
    shown = lambda: [r[0] for r in rows() if "shown" in r[2].split()]  # noqa: E731
    canvas = lambda: page.evaluate(CANVAS)  # noqa: E731
    jobs = lambda start: [t for t in U.log_lines(page)[start:] if t.startswith("Upscale: ") or "upscaled: about" in t]  # noqa: E731

    def switch(on):  # a person's path: the menu, the switch, the menu closed
        if not page.is_visible("#finish-upscale"):
            page.click("#finish-btn")
        if page.is_checked("#finish-upscale") != on:
            page.click("#finish-upscale")
        page.click("#finish-btn")
        if page.is_visible("#finish-upscale"):
            page.keyboard.press("Escape")

    page.click("#finish-btn"); page.click("#finish-upscale")
    status = page.text_content("#status") or ""
    U.check(names() == ["Plate, upscaled"] and status.startswith("Finish: Upscale on. Generate runs it on the plate: about "),
            f"before Generate, the Render panel shows the plate's upscaled step, and the status line what Generate runs: {names()}, {status!r}")
    custom(page, U, "1600")
    page.keyboard.press("Escape")
    page.click("#generate")
    U.wait_log(page, U.added_line("Plate, upscaled: done in"), 240000, "the plate's upscaled step")
    U.poll(page, lambda: shown() == ["Plate, upscaled"] and canvas() == [1600, 880], 3)
    U.check(shown() == ["Plate, upscaled"] and canvas() == [1600, 880] and (page.text_content("#status") or "").startswith("Plate, upscaled: ready, in the viewer."),
            f"the player shows the upscaled plate at its own size: {shown()}, {canvas()}, {page.text_content('#status')!r}")
    switch(False)
    U.poll(page, lambda: not names() and canvas() == [1280, 704], 3)
    U.check(not names() and canvas() == [1280, 704], f"Upscale off: no render, and the player shows the plate at its own size: {rows()}, {canvas()}")
    start = len(U.log_lines(page))
    switch(True)
    U.poll(page, lambda: shown() == ["Plate, upscaled"] and canvas() == [1600, 880], 3)
    page.wait_for_timeout(U.QUIET_MS)
    U.check(shown() == ["Plate, upscaled"] and canvas() == [1600, 880] and not jobs(start), f"on again, the step comes back made, with no new job: {rows()}, {canvas()}, {jobs(start)}")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    zipped = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(zip_rows.files(zipped, "plate_upscaled") and not jobs(start), f"Export posts no Upscale job, and zips the upscaled plate: {sorted({n.rsplit('/', 1)[0] for n in zipped})}")
    page.keyboard.press("F6")  # the wipe: the plate against the step on show
    page.wait_for_timeout(300)
    sides = page.evaluate("[document.querySelector('#wipe .label.left').textContent, document.querySelector('#wipe .label.right').textContent]")
    U.check(sides == ["Plate", "Plate, upscaled"], f"the wipe names the step on show, among the render's own steps: {sides}")
    page.close()
