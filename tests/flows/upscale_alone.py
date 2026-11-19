"""Finish > Upscale on a plate with no edit, with SDR to HDR on: there is no composite, so Export restores the end
output alone, SDR to HDR's frames, upscaled (3840 x 2112 for desk.mp4's 1280 x 704), and the zip holds them under upscaled/ beside
the frames at the plate's size, with no upscaled plate."""
import zipfile


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.click("#finish-btn")
    page.click("#finish-hdr"); page.click("#finish-hdr-yes")
    page.click("#finish-upscale")
    U.check("3840 x 2112" in (page.text_content("#finish-upscale-ask p") or ""), "the question gives the plate's upscaled size")
    page.click("#finish-upscale-yes"); page.keyboard.press("Escape")
    page.click("#generate")
    U.wait_log(page, "[...document.querySelectorAll('#log li span')].some((e) => /Render v\\d+: SDR to HDR: done in/.test(e.textContent))",
               120000, "SDR to HDR on the plate")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    lines = U.log_lines(page)[start:]
    U.check(any(t.startswith("Upscale: 3840 x 2112, ") for t in lines) and any(t.startswith("Upscale: done in ") for t in lines),
            f"Export restores the end output alone: {[t for t in lines if t.startswith('Upscale')]}")
    U.check(any(n.startswith("upscaled/export/") for n in names) and any(n.startswith("hdr/") for n in names) and not any(n.startswith("upscaled/plate/") for n in names),
            f"the zip holds the upscaled frames beside the frames at the plate's size, with no upscaled plate: {sorted({n.split('/')[0] + '/' + n.split('/')[1] for n in names if '/' in n})}")
    page.close()
