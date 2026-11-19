"""Finish > Upscale on a fluid shot: Export restores the shot alone upscaled (3840 x 2400 for a 512 x 320 blank plate)
and the zip holds it under upscaled/, beside the shot in the blank plate's format."""
import zipfile


def run(browser, port, U):
    page = U.load(browser, port)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.dispatch_event("#b-frames", "input")
    page.evaluate(U.WATCH)
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("under the edits: the fluid shot v"), 240000, "the fluid shot")
    page.click("#finish-btn"); page.click("#finish-upscale")
    U.check("3840 x 2400" in (page.text_content("#finish-upscale-ask p") or ""), "the question gives the fluid shot's upscaled size")
    page.click("#finish-upscale-yes"); page.keyboard.press("Escape")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    lines = U.log_lines(page)[start:]
    U.check(any(t.startswith("Upscale: 3840 x 2400, 1 job.") for t in lines) and any(t.startswith("Upscale: done in ") for t in lines),
            f"Export restores the fluid shot alone, in one job: {[t for t in lines if t.startswith('Upscale')]}")
    U.check(any(n.startswith("upscaled/export/") for n in names) and any(n.startswith("plate/") for n in names) and not any(n.startswith("upscaled/plate/") for n in names),
            f"the zip holds the upscaled shot beside the shot in the blank plate's format: {sorted({n.split('/')[0] + '/' + n.split('/')[1] for n in names if '/' in n})}")
    page.close()
