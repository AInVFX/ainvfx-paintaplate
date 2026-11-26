"""SDR to HDR's set for a Clean on desk.mp4, a plate whose format holds nothing above 1.0: after « Composite, HDR » and Export,
the set's composite rebuilds from its own plate, layer and matte, comp = plate x (1 - matte) + layer x matte, within half-float
rounding on the first, middle and last frames, and its plate and layer hold values above 1.0."""
import hdr_set  # noqa: E402


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.keyboard.press("c"); U.paint_once(page, "the cup", [(0.6, 0.4), (0.62, 0.45)]); page.wait_for_timeout(1500); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "SDR to HDR's steps on the elements")
    page.click("#export-btn")
    with page.expect_download(timeout=120000):
        page.click("#x-go")
    folder = hdr_set.folder_of(U.log_lines(page))
    worst, peak = hdr_set.rebuilt(port, folder, (1, 25, 49)) if folder else (1.0, 0.0)
    U.check(folder.endswith("/hdr") and worst <= 1e-3 and peak > 1.0,
            f"the set's composite rebuilds from its plate, layer and matte: largest difference {worst:.6f}, peak {peak:.2f}, in {folder!r}")
    page.close()
