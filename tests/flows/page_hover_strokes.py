"""Hovering a History row shows that edit's strokes on the first frame, for every tool: a Light edit's light too, while a
selected Light edit still shows its result alone. Hovering a fluid shot's row shows its first keyframe, here over the
blank plate, the fluid shot being bypassed."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import PIXEL  # noqa: E402

FLUID = '#history li[data-id="fluid"]'


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    away = lambda: (page.mouse.move(5, 5), page.wait_for_timeout(300))

    def row(n):  # History's row n; the rows are newest first
        titles = U.row_titles(page)
        return f"#history li:nth-child({next(k for k, t in enumerate(titles) if t.startswith(f'{n}.')) + 1})"

    def hovered(selector, at):  # the first frame's pixel at `at`, with the pointer on a row
        page.hover(selector); page.wait_for_timeout(300)
        got = pixel(at)
        away()
        return got

    # 1. A Light edit and a Paint edit, made, then bypassed: the first frame shows the plate where they were painted
    light_at, paint_at = (0.33, 0.315), (0.72, 0.61)
    page.click('.tools [data-tool="light"]')
    U.paint_once(page, "", [(0.3, 0.3), (0.33, 0.315), (0.36, 0.33)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.7, 0.6), (0.72, 0.61), (0.74, 0.62)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)
    for n in (2, 1):
        page.click(f"{row(n)} .eye")
    U.settled(page)
    page.keyboard.press("Home"); away()
    plate_light, plate_paint = pixel(light_at), pixel(paint_at)
    got = hovered(row(1), light_at)
    U.check(np.abs(got - plate_light).sum() > 8, f"hovering the Light edit's row shows its strokes: {got.tolist()} on a plate of {plate_light.tolist()}")
    got = hovered(row(2), paint_at)
    U.check(np.abs(got - plate_paint).sum() > 40, f"hovering the Paint edit's row shows its strokes: {got.tolist()} on a plate of {plate_paint.tolist()}")

    # 2. The Light edit on again, then selected: the frame shows its result alone, never its light added once more
    page.click(f"{row(1)} .eye")
    U.settled(page)
    page.keyboard.press("Home"); away()
    result = pixel(light_at)
    page.click(f"{row(1)} .edit"); away()
    U.check(np.abs(pixel(light_at) - result).sum() <= 6, f"a selected Light edit shows its result alone: {pixel(light_at).tolist()} against {result.tolist()}")
    page.keyboard.press("Escape")

    # 3. A fluid shot's row: hovering it shows its first keyframe
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    key_at = (0.5, 0.7)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End")
    U.stroke(page, [(0.45, 0.3), (0.55, 0.2)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    page.click(f"{FLUID} .eye")  # bypassed: the blank plate under the edits, as when every edit is bypassed
    U.wait_log(page, "[...document.querySelectorAll('#log li span')].some((e) => e.textContent.includes('under the edits: the blank plate'))", 60000, "blank plate")
    U.settled(page)
    page.keyboard.press("Home"); away()
    blank = pixel(key_at)
    got = hovered(FLUID, key_at)
    U.check(np.abs(got - blank).sum() > 30, f"hovering the fluid shot's row shows its first keyframe: {got.tolist()} on the blank plate's {blank.tolist()}")
    U.no_errors(errors, "after the hovers")
    page.close()
