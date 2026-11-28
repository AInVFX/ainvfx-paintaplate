"""A fluid shot's keyframes on the frames they are painted on. Hovering the fluid shot's row shows its keyframe on the
frame displayed, any keyframe and not only the first; on a frame with no keyframe, nothing is drawn. A click on the row
goes to its keyframe nearest the frame displayed, and the HUD names that keyframe."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import PIXEL  # noqa: E402

FLUID = '#history li[data-id="fluid"]'


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    away = lambda: (page.mouse.move(5, 5), page.wait_for_timeout(300))
    frame = lambda: int(page.text_content("#frame-now"))

    def go(n):  # the plate's frame n, with the arrow keys
        page.keyboard.press("Home")
        for _ in range(n - frame()):
            page.keyboard.press("ArrowRight")
        U.check(U.poll(page, lambda: frame() == n, 5), f"frame {n} displayed ({frame()})")

    def hovered(at):  # the pixel at `at`, with the pointer on the fluid shot's row
        page.hover(FLUID); page.wait_for_timeout(300)
        got = pixel(at)
        away()
        return got

    # A blank plate: a keyframe on the first frame, another near frame 17, then the fluid shot, bypassed so that only
    # what the hover draws changes a pixel of the blank plate
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    first_at, second_at = (0.3, 0.7), (0.7, 0.3)  # where each keyframe is painted
    U.paint_once(page, "thick white smoke", [(0.25, 0.72), (0.3, 0.7), (0.35, 0.72)])
    go(17)
    U.stroke(page, [(0.65, 0.32), (0.7, 0.3), (0.75, 0.32)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    page.click(f"{FLUID} .eye")
    U.wait_log(page, "[...document.querySelectorAll('#log li span')].some((e) => e.textContent === 'Fluid shot v1 is bypassed.')", 60000, "the fluid shot bypassed")
    U.settled(page)

    # Where the keyframes landed, on the 8-frame grid, as the plate counts its frames
    page.keyboard.press("Home")
    first = frame()
    keys = sorted(int(f) for f in page.eval_on_selector_all("#tl-keys .tl-kf", "els => els.map(e => e.dataset.frame)"))
    U.check(len(keys) == 2 and keys[0] == 0 and keys[1] > 8, f"two keyframes, on the first frame and a later one: {keys}")
    later = first + keys[1]

    # 1. The later keyframe's frame: hovering the row shows the keyframe painted there
    go(later); away()
    blank = pixel(second_at)
    got = hovered(second_at)
    U.check(np.abs(got - blank).sum() > 30, f"hovering the fluid shot's row on frame {later} shows the keyframe painted there: {got.tolist()} on the blank plate's {blank.tolist()}")

    # 2. A frame with no keyframe: hovering the row draws nothing, where either keyframe is painted
    go(first + 9); away()
    blank = [pixel(first_at), pixel(second_at)]
    got = [hovered(first_at), hovered(second_at)]
    U.check(all(np.abs(g - b).sum() <= 6 for g, b in zip(got, blank)), f"on frame {first + 9}, with no keyframe, the hover draws nothing: {[g.tolist() for g in got]} against {[b.tolist() for b in blank]}")

    # 3. A click on the row, on a frame nearer the later keyframe, goes to that keyframe, and the HUD names it
    go(later - 4)
    page.click(f"{FLUID} .title")
    U.check(U.poll(page, lambda: frame() == later, 5) and f"keyframe {later} displayed" in page.text_content("#hud"),
            f"a click on the fluid shot's row goes to its nearest keyframe, frame {later}: frame {frame()}, HUD « {page.text_content('#hud')} »")
    U.no_errors(errors, "after the hovers and the click")
    page.close()
