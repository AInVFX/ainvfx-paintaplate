"""Upscale in windows that share frames, with an edit's matte: on a 16 GB GPU with 16 GB of RAM, a paint on desk.mp4
upscaled to 1600 runs in windows of at most 21 frames, two neighbours sharing 4 frames. The zip's upscaled matte holds one
frame per frame of the shot, as the plate-size matte does, and frame by frame it is that matte's own frame: the mock writes
each upscaled matte frame in one grey, the mean of the plate-size frame it reads."""
import io
import re
import zipfile

import numpy as np
from PIL import Image

import zip_rows  # noqa: E402

SIZE = "() => { const s = document.querySelector('#finish-upscale-size'); return s?.options[s.selectedIndex]?.textContent ?? ''; }"


def grey(z, name):  # the mean of a frame in 8-bit levels, read as the mock reads the plate-size matte
    return round(float(np.asarray(Image.open(io.BytesIO(z.read(name))).convert("L"), np.float32).mean()))


def run(browser, port, U):
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 16 * 2 ** 30})
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-upscale")
    page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", "1600"); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
    U.poll(page, lambda: "1600 x " in page.evaluate(SIZE), 3)
    page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite of the paint")
    page.click("#export-btn"); page.check("#x-matte"); page.check("#x-full")
    with page.expect_download(timeout=280000) as dl:
        page.click("#x-go")
    lines = [t for t in U.log_lines(page) if t.startswith("Upscale: 1600 x ")]
    cut = [re.search(r", (\d+) windows of (\d+) frames, each in one pass\.", t) for t in lines]
    U.check(any(m and int(m[1]) >= 2 for m in cut), f"windows, two neighbours sharing 4 frames: {lines}")
    z = zipfile.ZipFile(dl.value.path())
    names = z.namelist()
    up, full = sorted(zip_rows.files(names, "matte_upscaled")), sorted(zip_rows.files(names, "matte"))
    U.check(full and len(up) == len(full), f"the upscaled matte holds one frame per frame of the shot, as the plate-size matte does: {len(up)} and {len(full)} frames")
    seen = [grey(z, a) for a in up]
    off = [i for i, (a, b) in enumerate(zip(seen, full)) if a != grey(z, b)]
    U.check(not off, f"each upscaled matte frame is the plate-size matte's own frame: frames {off[:8]} differ, greys {sorted(set(seen))[:8]}")
    page.close()
