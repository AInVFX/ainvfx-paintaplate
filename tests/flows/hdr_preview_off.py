"""The Preview menu with Finish > SDR to HDR on: Off plans no preview step, and SDR to HDR's steps stay as they are, after
« Composite, full size », to « finish ready »; Export reads SDR to HDR's composite, as Export is always full size."""
import hdr_set  # noqa: E402

RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"
NAMES = "els => els.map((e) => e.querySelector('.name').textContent)"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.select_option("#preview-size", "off")
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "SDR to HDR's steps, with no preview")
    page.wait_for_function(RESTS, timeout=60000)
    rows = page.eval_on_selector_all("#stages li", NAMES)
    U.check(not any(", preview" in x for x in rows) and rows[-4:] == ["Composite, full size", "Plate, HDR", "Layer, HDR", "Composite, HDR"],
            f"Preview off: no preview step, and SDR to HDR's steps after the full-size composite: {rows}")
    page.click("#export-btn")
    with page.expect_download(timeout=120000):
        page.click("#x-go")
    U.check(hdr_set.folder_of(U.log_lines(page)).endswith("/hdr"), "Export reads SDR to HDR's composite: its line names the set's composite")
    page.close()
