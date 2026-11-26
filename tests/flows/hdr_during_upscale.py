"""Finish > SDR to HDR turned on while one of Upscale's steps runs on the plate-size set: that step stops at once, as its set
is no longer the last stage, whichever job it runs (the export's parts it fetches first, or a window); SDR to HDR's steps run, then Upscale's on SDR to HDR's set, to « finish ready ». The first of
Upscale's jobs is held 8 s on the mock, so the switch meets it running. 1600 x 880, a size the mock holds in a small machine."""
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"
NAMES = "els => els.map((e) => e.querySelector('.name').textContent)"
SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"
finish = lambda rows: [x for x in rows[rows.index("Composite, full size") + 1:] if x != "Export"] if "Composite, full size" in rows else []  # noqa: E731  # the Finish steps' rows


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-upscale")
    page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", "1600"); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
    U.poll(page, lambda: "1600 x " in page.evaluate(SIZE), 3)
    page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite")
    U.mock_route(port, "/mock/hold", {"output": "frames", "seconds": 8, "times": 1})  # the next job with frames: the plate's first window
    U.wait_log(page, U.added_line("Plate, upscaled: about"), 120000, "the first of Upscale's steps")
    start = len(U.log_lines(page))
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    U.wait_log(page, U.added_line("Composite, HDR, upscaled: done in"), 300000, "Upscale on SDR to HDR's set")
    page.wait_for_function(RESTS, timeout=60000)
    lines, rows = U.log_lines(page)[start:], page.eval_on_selector_all("#stages li", NAMES)
    stopped = [t for t in lines if t.startswith(("upscale ", "export ")) and ": stopped after " in t]  # the step's job: the export's parts it fetches first, or a window
    want = ["Plate, HDR", "Layer, HDR", "Composite, HDR", "Plate, HDR, upscaled", "Layer, HDR, upscaled", "Composite, HDR, upscaled"]
    U.check(stopped and finish(rows) == want and page.text_content("#render-left") == "finish ready",
            f"the running Upscale step stops at once, then SDR to HDR's steps and Upscale's on its set: {stopped[:1]}, {finish(rows)}, {[t[:50] for t in lines if t.startswith(('upscale ', 'export '))][:6]}")
    page.close()
