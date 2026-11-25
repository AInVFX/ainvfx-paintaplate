"""The wipe's left side shows a History row's strokes over the plate. Ctrl+click on the row puts them there, and comma
steps to them after the plate and the Render panel's steps. A fluid shot's keyframes show on their own frames, over the
black blank plate; a Paint edit's strokes show on the first frame. The labels name what each side shows."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import PIXEL  # noqa: E402

FLUID = '#history li[data-id="fluid"]'
SIDES = "[document.querySelector('#wipe .label.left').textContent, document.querySelector('#wipe .label.right').textContent]"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    frame = lambda: int(page.text_content("#frame-now"))
    sides = lambda: page.evaluate(SIDES)

    def go(n):  # the plate's frame n, with the arrow keys
        page.keyboard.press("Home")
        for _ in range(n - frame()):
            page.keyboard.press("ArrowRight")
        U.check(U.poll(page, lambda: frame() == n, 5), f"frame {n} displayed ({frame()})")

    # A blank plate: a keyframe on the first frame, another near frame 17, the fluid shot, then a Paint edit on it.
    # Every stroke is left of the wipe's line, on its left side
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    later_at, paint_at = (0.25, 0.3), (0.35, 0.5)
    U.paint_once(page, "thick white smoke", [(0.15, 0.72), (0.2, 0.7), (0.25, 0.72)])
    go(17)
    U.stroke(page, [(0.2, 0.32), (0.25, 0.3), (0.3, 0.32)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    U.settled(page)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.33, 0.5), (0.35, 0.5), (0.37, 0.5)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)
    page.keyboard.press("Home")
    first = frame()
    keys = sorted(int(f) for f in page.eval_on_selector_all("#tl-keys .tl-kf", "els => els.map(e => e.dataset.frame)"))
    later = first + keys[-1]

    # 1. F6, then Ctrl+click on the fluid shot's row: its keyframes on the left side, named, over the black blank plate
    page.keyboard.press("F6")
    U.check(U.poll(page, lambda: sides()[0] == "Plate", 5), f"F6: the plate on the left ({sides()})")
    page.click(f"{FLUID} .title", modifiers=["Control"])
    U.check(U.poll(page, lambda: sides()[0] == "Fluid 1, keyframes", 5) and "Press Esc or F6 to end it." in page.text_content("#hud")
            and page.eval_on_selector(FLUID, "e => e.classList.contains('compared')"),
            f"Ctrl+click on the fluid shot's row puts its keyframes on the left side, named, and marks the row: {sides()}, HUD « {page.text_content('#hud')} »")
    go(later)
    got = pixel(later_at)
    U.check(got.min() > 150, f"on frame {later}, the left side shows the keyframe painted there, at full strength: {got.tolist()}")
    go(first + 9)
    got = pixel(later_at)
    U.check(got.max() < 20, f"on frame {first + 9}, with no keyframe there, the left side shows the black blank plate: {got.tolist()}")
    page.click(f"{FLUID} .title", modifiers=["Control"])
    U.check(U.poll(page, lambda: sides()[0] == "Plate", 5), f"a second Ctrl+click on the row ends it: {sides()}")

    # 2. Comma steps the left side from the plate through the Render steps to each row's strokes, in History's order
    page.keyboard.press("Home")
    seen = []
    for _ in range(20):
        page.keyboard.press(",")
        page.wait_for_timeout(150)
        seen.append(sides()[0])
        if seen[-1] == "Paint 2, strokes":
            break
    U.check(seen[-1] == "Paint 2, strokes" and seen.index("Fluid 1, keyframes") < len(seen) - 1,
            f"comma steps the left side to the fluid shot's keyframes, then to the Paint edit's strokes: {seen}")
    got = pixel(paint_at)
    U.check(got.min() > 150, f"on the first frame, the left side shows the Paint edit's strokes over the plate: {got.tolist()}")
    U.no_errors(errors, "after the wipe")
    page.close()
