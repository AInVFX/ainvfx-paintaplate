"""A press and a lift with no move paints one dab of the brush, as a stroke does: with Paint, Clean and Light, on a fluid
keyframe, and with the eraser, which takes a dab away. The frame shows each dab where the click was."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import PIXEL  # noqa: E402


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    box = U.view_box(page)
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))

    def click(at):  # a press and a lift at one point, then the pointer away from the frame, so its cursor hides nothing
        page.mouse.move(box["x"] + at[0] * box["w"], box["y"] + at[1] * box["h"]); page.mouse.down(); page.mouse.up()
        page.mouse.move(5, 5); page.wait_for_timeout(250)

    # 1. Paint: a dab of the brush's colour, and the prompt writer asked for a box around it
    page.click('.tools [data-tool="paint"]')
    page.fill("#prompt", "a red ball"); page.evaluate("document.activeElement.blur()")
    at = (0.3, 0.5); plate = pixel(at)
    page.evaluate(U.WATCH)
    click(at)
    U.check(np.abs(pixel(at) - plate).sum() > 40, f"a click with Paint leaves a dab on the frame: {pixel(at).tolist()} on a plate of {plate.tolist()}")
    U.wait_log(page, U.added_line("asking Klein's prompt writer"), 30000, "prompt writer's request")
    asked = [t for t in page.evaluate("window.__lines") if "asking Klein's prompt writer" in t]
    U.check("[0,0,1000,1000]" not in asked[-1], f"the prompt writer gets a box around the dab, not the whole frame: {asked[-1]}")

    # 2. The eraser: a click on the dab takes it away
    page.click("#rub-btn")
    click(at)
    U.check(np.abs(pixel(at) - plate).sum() <= 12, f"a click with the eraser takes the dab away: {pixel(at).tolist()} against the plate's {plate.tolist()}")
    page.keyboard.press("Escape")

    # 3. Light and Clean: a dab each
    for tool, words, at, least in (("light", "", (0.5, 0.5), 20), ("erase", "the bottle", (0.7, 0.5), 40)):
        page.click(f'.tools [data-tool="{tool}"]')
        page.fill("#prompt", words); page.evaluate("document.activeElement.blur()")
        plate = pixel(at)
        click(at)
        U.check(np.abs(pixel(at) - plate).sum() > least, f"a click with {tool} leaves a dab on the frame: {pixel(at).tolist()} on a plate of {plate.tolist()}")
        page.keyboard.press("Escape")

    # 4. A fluid keyframe on a blank plate: a dab of the keyframe's colour
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    box = U.view_box(page)
    at = (0.5, 0.5); plate = pixel(at)
    click(at)
    U.check(np.abs(pixel(at) - plate).sum() > 40, f"a click on a fluid keyframe leaves a dab of its colour: {pixel(at).tolist()} on a blank plate of {plate.tolist()}")
    U.no_errors(errors, "after the clicks")
    page.close()
