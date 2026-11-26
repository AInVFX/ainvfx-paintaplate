"""Finish > Upscale on the mock: the row is off and asks in figures before it turns on; at Export, one step in the
Render panel restores the plate and the layer window by window (a 16 GB GPU with 52 GB of RAM: windows of 21 frames),
composes the upscaled result, and the zip holds the upscaled set beside the plate-size result and its layer. A second render takes the plate's windows from the job index."""
import zipfile
import zip_rows  # noqa: E402


def run(browser, port, U):
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 52 * 2 ** 30})
    page = U.load(browser, port)
    page.on("console", lambda m: None)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    page.evaluate(U.WATCH)
    page.click("#finish-btn")
    U.check(page.is_enabled("#finish-upscale") and not page.is_checked("#finish-upscale"), "Upscale is a row of the Finish menu, off")
    start = len(U.log_lines(page))
    page.click("#finish-upscale")
    note = page.text_content("#finish-upscale-time") or ""
    U.check(page.is_hidden("#finish-upscale-ask") and page.is_checked("#finish-upscale") and page.text_content("#finish-btn") == "Finish · 1"
            and any(t.startswith("Finish: Upscale on.") for t in U.log_lines(page)[start:]), "its switch turns it on with no question, and the log says so")
    U.check(note.startswith("About ") and note.endswith(" min on this GPU."), f"the note under the size list gives the time on this GPU: {note!r}")
    page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite of the paint")
    page.click("#export-btn"); page.check("#x-matte")  # beside the composite, upscaled, which the dialog opens on
    with page.expect_download(timeout=280000) as dl:
        page.click("#x-go")
    lines = U.log_lines(page)
    U.check(any(t.startswith("Upscale: 3840 x 2112, 3 windows of 19 frames, each in one pass.") for t in lines), f"the windows follow the machine's memory: {[t for t in lines if 'Upscale:' in t]}")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    parts = {zip_rows.row_of(n) for n in names if zip_rows.row_of(n).endswith("_upscaled")}
    mattes = zip_rows.files(names, "matte_upscaled")
    U.check(parts == {"composite_upscaled", "matte_upscaled"} and len(mattes) == 49 and not any(n.startswith("layer") for n in names),
            f"the zip holds the upscaled result and its matte, numbered on across the windows, and no layer: {sorted(parts)}, {len(mattes)} matte frames")
    status = page.text_content("#status") or ""
    said = [t for t in U.log_lines(page) if t.startswith("Download: ")][-1:]
    U.check(status.startswith("Download: ") and status.endswith(".zip.") and said and "Composite, upscaled." in said[0],
            f"the status line names the zip, and the log names the rows it holds, the upscaled set among them: {status!r}, {said!r}")
    start = len(U.log_lines(page))
    page.keyboard.press("c"); U.paint_once(page, "the cup", [(0.6, 0.4), (0.62, 0.45)]); page.wait_for_timeout(1500); page.keyboard.press("Enter")
    U.wait_log(page, f"window.__lines.filter((t) => {U.HAS_REVIEWED}).length >= 2", 240000, "the full-size composite of both edits")
    page.click("#export-btn")
    with page.expect_download(timeout=280000) as dl:
        page.click("#x-go")
    taken = [t for t in U.log_lines(page)[start:] if t.startswith("upscale: taken from the job index")]
    names = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(len(taken) == 3 and zip_rows.files(names, "composite_upscaled"), f"the next render takes the plate's 3 windows from the job index: {len(taken)}")
    page.close()
