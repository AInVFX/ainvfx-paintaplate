"""Finish > Upscale with SDR to HDR on a Paint: SDR to HDR's result regenerates every pixel, so the render's one upscaled step,
« Composite, upscaled », upscales the result itself with its matte, and keeps its values above 1.0 everywhere. Export posts no
Upscale job, and the zip's upscaled set holds no plate and no layer. The mock writes a joined set as a movie, whatever format the
page asks for; the GPU runs read it as EXR frames."""
import zipfile

NAMES = "els => els.map((e) => e.querySelector('.name').textContent)"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)  # the log's new lines, for the waits
    page.click("#finish-btn")
    page.click("#finish-hdr"); page.click("#finish-hdr-yes")
    page.click("#finish-upscale")
    page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, upscaled: done in"), 300000, "the render's upscaled step, after SDR to HDR and the composite")
    rows, lines = page.eval_on_selector_all("#stages li", NAMES), U.log_lines(page)
    U.check(any("SeedVR2 7B upscales the result." in t for t in lines) and "Composite, upscaled" in rows and not {"Plate, upscaled", "Layer, upscaled"} & set(rows),
            f"the render upscales SDR to HDR's result alone: {rows}, {[t for t in lines if t.startswith('Upscale')]}")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    parts = {n.split("/")[1] for n in zipfile.ZipFile(dl.value.path()).namelist() if n.startswith("upscaled/")}
    U.check(parts == {"export", "matte"} and not any(t.startswith("Upscale: ") for t in U.log_lines(page)[start:]),
            f"Export writes the upscaled result and its matte, no plate and no layer, with no Upscale job: {sorted(parts)}")
    page.close()
