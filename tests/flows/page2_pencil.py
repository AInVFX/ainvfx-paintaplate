"""The pencil selects an edit and shows its strokes at once: on the first frame, over the picture it paints on, the edits
below it, with no result of its own or of the edits above; a Light's strokes too. On a fluid shot, the pencil goes to the
keyframe nearest the frame displayed and shows it on the black plate, and the chip names the fluid shot."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import PIXEL  # noqa: E402

ROW = "#history li:has(.title:text-is('{}')) .edit"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    away = lambda: (page.mouse.move(5, 5), page.wait_for_timeout(300))
    a, b, c = (0.33, 0.5), (0.63, 0.5), (0.18, 0.21)  # inside each edit's stroke
    plate_b = pixel(b)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.30, 0.5), (0.36, 0.5)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.paint_once(page, "a blue cube", [(0.60, 0.5), (0.66, 0.5)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    page.keyboard.press("l"); U.paint_once(page, "warm light", [(0.15, 0.2), (0.21, 0.22)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=3), timeout=120000)
    U.settled(page)
    page.keyboard.press("Home"); away()
    light_made = pixel(c)

    # 1. The pencil on edit 1: the plate under it, edit 2's result gone, its own strokes at full strength
    page.click(ROW.format("1. Paint")); away()
    color = page.input_value("#color")
    paint = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)])
    got_a, got_b = pixel(a), pixel(b)
    U.check(page.text_content("#editing") == "Editing 1 · Paint" and np.abs(got_b - plate_b).sum() <= 12 and np.abs(got_a - paint).sum() <= 30,
            f"the pencil on edit 1 shows the plate under it, edit 2 gone ({got_b.tolist()} on {plate_b.tolist()}), its strokes in {color} ({got_a.tolist()})")

    # 2. The pencil on the Light edit: its strokes show, where its result showed alone
    page.click(ROW.format("3. Light")); away()
    got_c = pixel(c)
    U.check(page.text_content("#editing") == "Editing 3 · Light" and np.abs(got_c - light_made).sum() > 30,
            f"the pencil on the Light edit shows its strokes, not its result: {got_c.tolist()} where its result was {light_made.tolist()}")
    page.keyboard.press("Escape")
    page.close()

    # 3. A fluid shot: from frame 14, the pencil goes to its keyframe on frame 18 and shows it on the black plate
    page = U.load(browser, port, errors=errors)
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    frame = lambda: int(page.text_content("#frame-now"))
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.25, 0.72), (0.3, 0.7), (0.35, 0.72)])
    page.keyboard.press("Home")
    for _ in range(16):
        page.keyboard.press("ArrowRight")
    U.stroke(page, [(0.65, 0.32), (0.7, 0.3), (0.75, 0.32)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    U.settled(page)
    page.keyboard.press("Home")
    for _ in range(13):
        page.keyboard.press("ArrowRight")
    page.click(ROW.format("1. Fluid")); page.mouse.move(5, 5); page.wait_for_timeout(300)
    on_key, off_key = pixel((0.7, 0.3)), pixel((0.5, 0.5))
    U.check(frame() == 18 and page.text_content("#editing") == "Editing 1 · Fluid" and on_key.min() > 150 and off_key.max() < 20
            and page.text_content("#status").startswith("Fluid shot selected: change its keyframes or its text prompt, then press Enter."),
            f"the pencil on the fluid shot goes to its keyframe nearest frame 14 ({frame()}), shows it on the black plate ({on_key.tolist()}, {off_key.tolist()}), and the chip names it ({page.text_content('#editing')!r})")
    U.no_errors(errors, "after the pencils")
    page.close()
