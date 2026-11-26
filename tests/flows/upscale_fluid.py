"""Finish > Upscale on a fluid shot alone: once the fluid shot is made, its render has one more step, « Plate, upscaled »,
which runs with no Generate and no Export, and which the player shows at its own size: 3456 x 2160 for a 512 x 320 blank plate, the
short side at most 2160. Export posts no Upscale job, and the zip holds the upscaled shot, named after its step, beside the shot in the
blank plate's format."""
import zipfile
import zip_rows  # noqa: E402

ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"
CANVAS = "() => { const c = document.querySelector('canvas[data-picture]'); return [c.width, c.height]; }"


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
    U.wait_log(page, U.added_line("Fluid shot, full size: done in"), 240000, "the fluid shot")
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    shown = lambda: [r[0] for r in rows() if "shown" in r[2].split()]  # noqa: E731
    page.click("#finish-btn"); page.click("#finish-upscale")
    U.check("3456 x 2160" in page.evaluate(SIZE), "the size list chooses the fluid shot's upscaled size")
    page.keyboard.press("Escape")
    U.wait_log(page, U.added_line("Plate, upscaled: done in"), 240000, "the fluid shot's upscaled step, with no Generate and no Export")
    U.poll(page, lambda: shown() == ["Plate, upscaled"] and page.evaluate(CANVAS) == [3456, 2160], 3)
    names = [r[0] for r in rows()]
    U.check(names[-2:] == ["Fluid shot, full size", "Plate, upscaled"] and shown() == ["Plate, upscaled"] and page.evaluate(CANVAS) == [3456, 2160],
            f"the upscaled step follows the fluid shot, and the player shows it at its own size: {names}, {shown()}, {page.evaluate(CANVAS)}")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    zipped = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(not any(t.startswith("Upscale: ") for t in U.log_lines(page)[start:]) and zip_rows.files(zipped, "plate_upscaled")
            and zip_rows.files(zipped, "fluid_shot") and not zip_rows.files(zipped, "fluid_shot_upscaled"),
            f"Export posts no Upscale job, and zips the upscaled shot beside the shot: {sorted({n.rsplit('/', 1)[0] for n in zipped})}")
    page.close()
