"""Finish > Upscale to 4K on the mock: the row is off and asks in figures before it turns on; at Export, one step in the
Render panel restores the plate and the layer window by window (a 16 GB GPU with 52 GB of RAM: windows of 21 frames),
composes the 4K result, and the zip holds the 4K set beside the plate-size result and its layer. A second render's export
takes the plate's windows from the job index."""
import zipfile


def run(browser, port, U):
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 52 * 2 ** 30})
    page = U.load(browser, port)
    page.on("console", lambda m: None)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    page.evaluate(U.WATCH)
    page.click("#finish-btn")
    U.check(page.is_enabled("#finish-upscale") and not page.is_checked("#finish-upscale"), "Upscale to 4K is a row of the Finish menu, off")
    page.click("#finish-upscale")
    ask = page.text_content("#finish-upscale-ask p") or ""
    U.check(page.is_visible("#finish-upscale-ask") and "a 4k folder at 3840 x 2112" in ask and "49 frames take about" in ask and "Every pixel" in ask,
            f"turning it on asks first, in figures: {ask!r}")
    start = len(U.log_lines(page))
    page.click("#finish-upscale-yes")
    U.check(page.is_checked("#finish-upscale") and page.text_content("#finish-btn") == "Finish · 1"
            and any(t.startswith("Finish: Upscale to 4K on.") for t in U.log_lines(page)[start:]), "« Yes, turn it on » turns it on, and the log says so")
    page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite of the paint")
    page.click("#export-btn")
    with page.expect_download(timeout=280000) as dl:
        page.click("#x-go")
    lines = U.log_lines(page)
    U.check(any(t.startswith("Upscale to 4K: 3840 x 2112, 3 windows of 21 frames.") for t in lines), f"the windows follow the machine's memory: {[t for t in lines if 'Upscale to 4K:' in t]}")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    parts = {n.split("/")[1] for n in names if n.startswith("4k/")}
    mattes = [n for n in names if n.startswith("4k/matte/")]
    U.check(parts == {"export", "plate", "layer", "matte"} and len(mattes) == 49 and any(n.startswith("layer/") for n in names),
            f"the zip holds the layer and the 4K set, its matte numbered on across the windows: {sorted(parts)}, {len(mattes)} matte frames")
    status = page.text_content("#status") or ""
    U.check(status.startswith("Download: ") and "its layer" in status and "the 4K set" in status, f"the download line names them: {status!r}")
    page.keyboard.press("c"); U.paint_once(page, "the cup", [(0.6, 0.4), (0.62, 0.45)]); page.wait_for_timeout(1500); page.keyboard.press("Enter")
    U.wait_log(page, f"window.__lines.filter((t) => {U.HAS_REVIEWED}).length >= 2", 240000, "the full-size composite of both edits")
    start = len(U.log_lines(page))
    page.click("#export-btn")
    with page.expect_download(timeout=280000) as dl:
        page.click("#x-go")
    taken = [t for t in U.log_lines(page)[start:] if t.startswith("upscale: taken from the job index")]
    names = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(len(taken) == 3 and any(n.startswith("4k/plate/") for n in names), f"the next export takes the plate's 3 windows from the job index: {len(taken)}")
    page.close()
