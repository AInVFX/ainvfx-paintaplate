"""Finish > Upscale on the mock, in windows that share frames. The row is off and turns on with no question, and its note
gives the time on this GPU. On a 16 GB GPU with 24 GB of RAM, a paint on desk.mp4 (49 frames) upscaled to 1600 x 880 runs
in 3 windows of 19 frames, two neighbours sharing 4 frames. At Export the zip holds the upscaled result and its matte, and
no layer: one upscaled matte frame per frame of the shot, each the plate-size matte's own frame (the mock writes each
upscaled matte frame in one grey, the mean of the plate-size frame it reads). The status line names the zip, and the log
its rows. A second render takes the plate's 3 windows from the job index."""
import io
import zipfile

import numpy as np
from PIL import Image

import zip_rows  # noqa: E402

SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"


def grey(z, name):  # the mean of a frame in 8-bit levels, read as the mock reads the plate-size matte
    return round(float(np.asarray(Image.open(io.BytesIO(z.read(name))).convert("L"), np.float32).mean()))


def run(browser, port, U):
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 24 * 2 ** 30})  # windows of 21 frames at 1600 x 880
    page = U.load(browser, port, "?blank=0&memory=small")  # a 16 GB GPU: no model warms up when the page loads
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
    page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", "1600"); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
    U.poll(page, lambda: "1600 x " in page.evaluate(SIZE), 3)
    page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite of the paint")
    page.click("#export-btn"); page.check("#x-matte"); page.check("#x-full")  # the matte at full size too, which the upscaled matte is read against
    with page.expect_download(timeout=280000) as dl:
        page.click("#x-go")
    lines = [t for t in U.log_lines(page) if t.startswith("Upscale: ")]
    U.check(any(t.startswith("Upscale: 1600 x 880, upscaled from 534 x 294, 3 windows of 19 frames, each in one pass.") for t in lines),
            f"the windows follow the machine's memory: {lines}")
    z = zipfile.ZipFile(dl.value.path())
    names = z.namelist()
    parts = {zip_rows.row_of(n) for n in names if zip_rows.row_of(n).endswith("_upscaled")}
    up, full = sorted(zip_rows.files(names, "matte_upscaled")), sorted(zip_rows.files(names, "matte"))
    U.check(parts == {"composite_upscaled", "matte_upscaled"} and not any("layer" in zip_rows.row_of(n) for n in names),
            f"the zip holds the upscaled result and its matte, and no layer: {sorted(parts)}")
    U.check(len(up) == len(full) == 49, f"the upscaled matte holds one frame per frame of the shot, as the plate-size matte does: {len(up)} and {len(full)} frames")
    seen = [grey(z, a) for a in up]
    off = [i for i, (a, b) in enumerate(zip(seen, full)) if a != grey(z, b)]
    U.check(not off, f"each upscaled matte frame is the plate-size matte's own frame: frames {off[:8]} differ, greys {sorted(set(seen))[:8]}")
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
