"""Finish > SDR to HDR turned on after a render whose Upscale ran on the plate-size set: SDR to HDR's steps run, then Upscale's
again, on SDR to HDR's set, with jobs of their own. Off again: the plate-size set's upscaled steps come back made, with no new
job. Each stage keeps its own upscaled results, as its set has its own folder. It asks for 1600 x 880, a size the mock holds
in a small machine's memory."""
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"
NAMES = "els => els.map((e) => e.querySelector('.name').textContent)"
finish = lambda rows: rows[rows.index("Composite, full size") + 1:] if "Composite, full size" in rows else []  # noqa: E731  # the Finish steps' rows
SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"


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
    U.wait_log(page, U.added_line("Composite, upscaled: done in"), 240000, "Upscale on the plate-size set")
    page.wait_for_function(RESTS, timeout=60000)
    start = len(U.log_lines(page))
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    U.wait_log(page, U.added_line("Composite, HDR, upscaled: done in"), 300000, "Upscale again, on SDR to HDR's set")
    page.wait_for_function(RESTS, timeout=60000)
    rows, jobs = page.eval_on_selector_all("#stages li", NAMES), [t for t in U.log_lines(page)[start:] if t.startswith("upscale ") and " done in " in t]
    want = ["Plate, HDR", "Layer, HDR", "Composite, HDR", "Plate, HDR, upscaled", "Layer, HDR, upscaled", "Composite, HDR, upscaled"]
    U.check(finish(rows) == want and len(jobs) > 0, f"turned on after: SDR to HDR's steps, then Upscale's on its set, with jobs of their own: {finish(rows)}, {len(jobs)} upscale jobs")
    start = len(U.log_lines(page))
    page.click("#finish-btn"); page.click("#finish-hdr"); page.keyboard.press("Escape")
    page.wait_for_function(RESTS, timeout=30000)
    page.wait_for_timeout(1500)
    rows, lines = page.eval_on_selector_all("#stages li", NAMES), U.log_lines(page)[start:]
    U.check(finish(rows) == ["Plate, upscaled", "Layer, upscaled", "Composite, upscaled"] and page.text_content("#render-left") == "finish ready"
            and not any(t.startswith(("upscale ", "upscale_export ")) for t in lines), f"off again: the plate-size set's upscaled steps come back made, with no new job: {finish(rows)}")
    page.close()
