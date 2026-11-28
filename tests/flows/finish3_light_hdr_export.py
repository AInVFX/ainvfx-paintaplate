"""Export after a Light edit with SDR to HDR on: the relit composite goes through SDR to HDR whole and is exported whole, with
no matte at full size or in SDR to HDR's set. With every tick the dialog offers (the matte's among them, for the preview's
matte), the zip downloads, SDR to HDR's composite in it, and no matte of a stage the export did not write."""
import zipfile

import zip_rows  # noqa: E402

RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.keyboard.press("l"); U.paint_once(page, "warm light", [(0.15, 0.2), (0.21, 0.22)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "the relit composite through SDR to HDR")
    page.wait_for_function(RESTS, timeout=60000)
    page.click("#export-btn")
    ticked = [box for box in ["#x-matte", "#x-preview", "#x-graph"] if page.is_visible(box)]
    for box in ticked:
        page.check(box)
    with page.expect_download(timeout=120000) as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    status = page.text_content("#status") or ""
    U.check(zip_rows.files(names, "composite_hdr") and not status.startswith("Error") and not zip_rows.files(names, "matte"),
            f"the zip downloads with every tick offered ({ticked}), SDR to HDR's composite in it: {status!r}, {sorted({zip_rows.row_of(n) for n in names})}")
    page.close()
