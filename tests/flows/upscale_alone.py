"""Finish > Upscale on a plate with no edit, with SDR to HDR on: the plate alone's render makes « Plate, HDR », then « SDR to HDR,
upscaled », SDR to HDR's frames upscaled with no Export, which the player shows at their own size. Export posts no Upscale job, and
the zip holds them, named after their step, beside the frames at the plate's size, with no upscaled plate. It asks for 1600 x 880, a size
above the plate's 1280 x 704 that the mock holds in a small machine's memory."""
import zipfile
import zip_rows  # noqa: E402

ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"
CANVAS = "() => { const c = document.querySelector('canvas[data-picture]'); return [c.width, c.height]; }"


def custom(page, U, px):  # Finish > Upscale's size, typed in Custom…, with the menu open
    page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", px); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
    U.poll(page, lambda: f"{px} x " in page.evaluate(SIZE), 3)


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    names = lambda: [r[0] for r in rows()]  # noqa: E731
    shown = lambda: [r[0] for r in rows() if "shown" in r[2].split()]  # noqa: E731
    page.click("#finish-btn")
    page.click("#finish-hdr"); page.click("#finish-hdr-yes")
    page.click("#finish-upscale")
    status = page.text_content("#status") or ""
    U.check("3840 x 2112" in page.evaluate(SIZE), "the size list chooses the plate's upscaled size")
    U.check(names() == ["Plate, HDR", "Plate, HDR, upscaled"] and status.startswith("Finish: Upscale on. Generate runs SDR to HDR and Upscale on the plate: about "),
            f"before Generate, the Render panel shows both steps, and the status line what Generate runs: {names()}, {status!r}")
    custom(page, U, "1600")
    page.keyboard.press("Escape")
    page.click("#generate")
    U.wait_log(page, U.added_line("Plate, HDR, upscaled: done in"), 240000, "SDR to HDR, then its upscaled step, on the plate")
    U.poll(page, lambda: shown() == ["Plate, HDR, upscaled"] and page.evaluate(CANVAS) == [1600, 880], 3)
    U.check(shown() == ["Plate, HDR, upscaled"] and page.evaluate(CANVAS) == [1600, 880] and (page.text_content("#status") or "").startswith("Plate, HDR, upscaled: ready, in the viewer."),
            f"the player shows SDR to HDR's frames upscaled, at their own size: {shown()}, {page.evaluate(CANVAS)}, {page.text_content('#status')!r}")
    start = len(U.log_lines(page))
    page.click("#export-btn"); page.check("#x-hdr")  # beside the upscaled frames, which the dialog opens on
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    zipped = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(not any(t.startswith("Upscale: ") for t in U.log_lines(page)[start:]) and zip_rows.files(zipped, "plate_hdr_upscaled")
            and zip_rows.files(zipped, "plate_hdr") and not zip_rows.files(zipped, "plate_upscaled"),
            f"Export posts no Upscale job, and zips the upscaled frames beside the frames at the plate's size: {sorted({n.split('/')[0] + '/' + n.split('/')[1] for n in zipped if '/' in n})}")
    page.close()
