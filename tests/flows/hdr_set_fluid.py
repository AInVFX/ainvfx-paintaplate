"""SDR to HDR's set for a Paint over a 16-bit fluid shot: the fluid shot is the plate, made once through SDR to HDR, and after
« Composite, HDR » and Export the set's composite rebuilds from its own plate, layer and matte, comp = plate x (1 - matte) +
layer x matte, within half-float rounding on the first, middle and last frames."""
import hdr_set  # noqa: E402


def run(browser, port, U):
    page = U.load(browser, port)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "16"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Plate, HDR: done in"), 120000, "the fluid shot through SDR to HDR")
    page.click(".tools [data-tool=paint]"); page.fill("#prompt", "a fire"); U.stroke(page, [(0.3, 0.5), (0.35, 0.45)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 180000, "SDR to HDR's steps on the elements")
    page.click("#export-btn")
    with page.expect_download(timeout=120000):
        page.click("#x-go")
    folder = hdr_set.folder_of(U.log_lines(page))
    worst, peak = hdr_set.rebuilt(port, folder, (1, 9, 17)) if folder else (1.0, 0.0)
    U.check(folder.endswith("/hdr") and worst <= 1e-3, f"the set's composite rebuilds from its plate, layer and matte: largest difference {worst:.6f}, in {folder!r}")
    page.close()
