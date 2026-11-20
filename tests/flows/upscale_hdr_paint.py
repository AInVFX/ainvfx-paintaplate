"""Finish > Upscale with SDR to HDR on a Paint: SDR to HDR's result regenerates every pixel, so Export restores the result
itself with its matte, and keeps its values above 1.0 everywhere: the zip's upscaled set holds no plate and no layer.
The mock writes a joined set as a movie, whatever format the page asks for; the GPU runs read it as EXR frames."""
import zipfile


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)  # the log's new lines, for the composite's wait
    page.click("#finish-btn")
    page.click("#finish-hdr"); page.click("#finish-hdr-yes")
    page.click("#finish-upscale")
    page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite of the paint, SDR to HDR among its steps")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    lines = U.log_lines(page)[start:]
    names = zipfile.ZipFile(dl.value.path()).namelist()
    parts = {n.split("/")[1] for n in names if n.startswith("upscaled/")}
    U.check(any("SeedVR2 upscales the result." in t for t in lines), f"Export upscales SDR to HDR's result alone: {[t for t in lines if t.startswith('Upscale')]}")
    U.check(parts == {"export", "matte"}, f"the upscaled set holds the result and its matte, no plate and no layer: {sorted(parts)}")
    page.close()
