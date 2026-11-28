"""Export takes Finish's sets by their layout (tests/flows/README.md): a Paint over a fluid shot, exported with every tick,
first with SDR to HDR on, then with Upscale on too, then with Upscale alone. Each time the zip holds each element at each
stage the render made, named after its step: « Plate, HDR », « Layer, HDR », « Composite, HDR » from SDR to HDR's set, and
« …, HDR, upscaled » or « …, upscaled » from Upscale's set of the stage it reads, beside the full size."""
import io
import zipfile

import zip_rows

TICKS = "[...document.querySelectorAll('#export label.check')].filter((l) => !l.hidden).map((l) => '#' + l.querySelector('input').id)"
FULL = ("fluid_shot_full_size", "shot_full_size", "layer_full_size", "matte", "composite_full_size")


def every_tick(page, U):  # Export with every tick the dialog shows: the zip's rows, or what the page said instead
    page.click("#export-btn")
    for tick in page.evaluate(TICKS):
        page.check(tick)
    try:
        with page.expect_download(timeout=120000) as dl:
            page.click("#x-go")
    except Exception as exc:
        raise AssertionError(f"no zip: {page.text_content('#status')!r}, {U.log_lines(page)[-6:]}") from exc
    names = zipfile.ZipFile(io.BytesIO(open(dl.value.path(), "rb").read())).namelist()
    return {zip_rows.row_of(n) for n in names}


def run(browser, port, U):
    page = U.load(browser, port)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Fluid shot, full size: done in"), 240000, "the fluid shot")
    page.click(".tools [data-tool=paint]"); page.fill("#prompt", "a red ball"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.45, 0.45), (0.55, 0.55)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the Paint's full-size composite")
    U.settled(page)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape"); page.click("#generate")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "SDR to HDR's set")
    rows = every_tick(page, U)
    hdr = ("plate_hdr", "layer_hdr", "composite_hdr")
    U.check(set(FULL + hdr) <= rows and not any("upscaled" in r for r in rows), f"SDR to HDR: each element at full size and in HDR: {sorted(rows)}")
    U.settled(page)
    page.click("#finish-btn"); page.click("#finish-upscale")
    U.upscale_custom(page, "1024")
    page.keyboard.press("Escape"); page.click("#generate")
    U.wait_log(page, U.added_line("Composite, HDR, upscaled: done in"), 300000, "Upscale on SDR to HDR's set")
    rows = every_tick(page, U)
    both = ("plate_hdr_upscaled", "layer_hdr_upscaled", "composite_hdr_upscaled", "matte_upscaled")
    U.check(set(FULL + hdr + both) <= rows and "composite_upscaled" not in rows, f"both: each element in HDR, then upscaled from SDR to HDR's set: {sorted(rows)}")
    U.settled(page)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.keyboard.press("Escape"); page.click("#generate")
    U.wait_log(page, U.added_line("Composite, upscaled: done in"), 300000, "Upscale on the full-size set")
    rows = every_tick(page, U)
    up = ("plate_upscaled", "layer_upscaled", "composite_upscaled", "matte_upscaled")
    U.check(set(FULL + up) <= rows and not any("hdr" in r for r in rows), f"Upscale alone: each element upscaled from the full-size set, nothing in HDR: {sorted(rows)}")
    page.close()
