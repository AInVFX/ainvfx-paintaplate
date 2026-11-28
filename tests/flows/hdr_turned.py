"""Finish > SDR to HDR turned off while one of its steps runs: the step stops at once, as Upscale's do, nothing more of SDR to
HDR runs, and the render rests at « full size ready ». On again, Generate runs its steps to « finish ready ». « Plate, HDR » is held 8 s
on the mock, so the switch meets it running."""
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"
NAMES = "els => els.map((e) => e.querySelector('.name').textContent)"
finish = lambda rows: rows[rows.index("Composite, full size") + 1:] if "Composite, full size" in rows else []  # noqa: E731  # the Finish steps' rows


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    U.mock_route(port, "/mock/hold", {"output": "hdr", "seconds": 8, "times": 1})
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Plate, HDR: about"), 240000, "the first of SDR to HDR's steps")
    start = len(U.log_lines(page))
    page.click("#finish-btn"); page.click("#finish-hdr"); page.keyboard.press("Escape")
    page.wait_for_function(RESTS, timeout=60000)
    page.wait_for_timeout(9000)  # longer than the held job: a step that went on would finish in it
    lines, left = U.log_lines(page)[start:], page.text_content("#render-left")
    U.check(left == "full size ready" and any(t.startswith("hdr ") and ": stopped after " in t for t in lines) and not any(" HDR: done in " in t for t in lines),
            f"turned off during « Plate, HDR »: the step stops at once, and nothing more of SDR to HDR runs: {left!r}, {[t[:70] for t in lines]}")
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape"); page.click("#generate")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "SDR to HDR's steps, asked for again with Generate")
    page.wait_for_function(RESTS, timeout=60000)
    rows = page.eval_on_selector_all("#stages li", NAMES)
    U.check(page.text_content("#render-left") == "finish ready" and finish(rows) == ["Plate, HDR", "Layer, HDR", "Composite, HDR"],
            f"on again, its steps run to « finish ready »: {finish(rows)}")
    page.close()
