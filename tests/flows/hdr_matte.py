"""A change of matte strategy with Finish > SDR to HDR on: another render, where the matte and the composite run again, then
« Layer, HDR » and « Composite, HDR » on the new export's parts, while « Plate, HDR » comes from the job index, as the plate
is the same. Back to the first strategy: its render shows at once, and nothing runs."""
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"
MENU = "#history li label.matte select"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "SDR to HDR's steps")
    page.wait_for_function(RESTS, timeout=60000)
    start = len(U.log_lines(page))
    page.evaluate(U.WATCH)  # the new render's lines only
    page.select_option(MENU, "Whole shot")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "SDR to HDR's steps on the new strategy's render")
    page.wait_for_function(RESTS, timeout=60000)
    lines = U.log_lines(page)[start:]
    ran = lambda name: any(f"{name}: done in" in t for t in lines)  # noqa: E731
    U.check(any(t.startswith("hdr: taken from the job index") for t in lines) and ran("Layer, HDR") and ran("Composite, HDR")
            and page.text_content("#render-left") == "finish ready",
            f"another strategy: « Layer, HDR » and « Composite, HDR » run again, « Plate, HDR » comes from the job index: {[t[:60] for t in lines if 'HDR' in t or 'hdr' in t]}")
    start = len(U.log_lines(page))
    page.select_option(MENU, "Auto")
    page.wait_for_timeout(3000)
    lines = U.log_lines(page)[start:]
    U.check(page.text_content("#render-left") == "finish ready" and not any(" done in " in t for t in lines),
            f"back to the first strategy: its render shows at once, and nothing runs: {[t[:60] for t in lines]}")
    page.close()
