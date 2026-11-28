"""Finish > Upscale turned on while one of SDR to HDR's steps runs: that step goes on, as it still stands, and Upscale's steps
join after SDR to HDR's, on its set, to « finish ready ». « Plate, HDR » is held 8 s on the mock, so the switch meets it
running. 1600 x 880, a size the mock holds in a small machine's memory."""
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"
NAMES = "els => els.map((e) => e.querySelector('.name').textContent)"
finish = lambda rows: [x for x in rows[rows.index("Composite, full size") + 1:] if x != "Export"] if "Composite, full size" in rows else []  # noqa: E731  # the Finish steps' rows


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    U.mock_route(port, "/mock/hold", {"output": "hdr", "seconds": 8, "times": 1})
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Plate, HDR: about"), 240000, "the first of SDR to HDR's steps")
    start = len(U.log_lines(page))
    page.click("#finish-btn"); page.click("#finish-upscale")
    U.upscale_custom(page, "1600")
    page.keyboard.press("Escape")
    U.wait_log(page, U.added_line("Composite, HDR, upscaled: done in"), 300000, "Upscale's steps on SDR to HDR's set")
    page.wait_for_function(RESTS, timeout=60000)
    lines, rows = U.log_lines(page)[start:], page.eval_on_selector_all("#stages li", NAMES)
    want = ["Plate, HDR", "Layer, HDR", "Composite, HDR", "Plate, HDR, upscaled", "Layer, HDR, upscaled", "Composite, HDR, upscaled"]
    U.check(not any(": stopped after " in t for t in lines) and any("Plate, HDR: done in" in t for t in lines) and finish(rows) == want
            and page.text_content("#render-left") == "finish ready",
            f"the running step of SDR to HDR goes on, then Upscale's steps on its set: {finish(rows)}, {[t[:50] for t in lines if 'stopped' in t]}")
    page.close()
