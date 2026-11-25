"""Finish > Upscale with SDR to HDR on a Paint: SDR to HDR runs first, on the elements, then Upscale on SDR to HDR's set. After
« Composite, full size » the render makes « Plate, HDR », « Layer, HDR » and « Composite, HDR », then « Plate, HDR, upscaled »,
« Layer, HDR, upscaled » and « Composite, HDR, upscaled », whose result is composed from the upscaled plate and layer with the
upscaled matte. Export posts no Upscale job, and the zip's upscaled set holds the result and its matte. It asks for 1600 x 880, a
size above the plate's 1280 x 704 that the mock holds in a small machine's memory with its six Finish steps. The mock writes a
joined set as a movie, whatever format the page asks for; the GPU runs read it as EXR frames."""
import zipfile
import zip_rows  # noqa: E402

NAMES = "els => els.map((e) => e.querySelector('.name').textContent)"
SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)  # the log's new lines, for the waits
    page.click("#finish-btn")
    page.click("#finish-hdr"); page.click("#finish-hdr-yes")
    page.click("#finish-upscale")
    page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", "1600"); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
    U.poll(page, lambda: "1600 x " in page.evaluate(SIZE), 3)
    page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR, upscaled: done in"), 300000, "Upscale's last step, after SDR to HDR's")
    rows = page.eval_on_selector_all("#stages li", NAMES)
    finish = ["Plate, HDR", "Layer, HDR", "Composite, HDR", "Plate, HDR, upscaled", "Layer, HDR, upscaled", "Composite, HDR, upscaled"]
    after = rows[rows.index("Composite, full size") + 1:] if "Composite, full size" in rows else []
    U.check(after[:6] == finish, f"SDR to HDR first, then Upscale, on each element: {rows}")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    parts = {zip_rows.row_of(n) for n in zipfile.ZipFile(dl.value.path()).namelist() if zip_rows.row_of(n).endswith("_upscaled")}
    U.check(len(parts) == 2 and "matte_upscaled" in parts and not any(t.startswith("Upscale: ") for t in U.log_lines(page)[start:]),
            f"Export writes the upscaled result and its matte, no plate and no layer, with no Upscale job: {sorted(parts)}")
    page.close()
