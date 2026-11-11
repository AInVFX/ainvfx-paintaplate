"""Edits are layers, after Generate. An edit above the edit made again is generated again when it depends on it, and it
stays hidden until its own pass ends: its History row says that it waits. An edit that does not depend on it stays on
the frame and is not generated again."""
import pathlib
import re
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import OPEN, PIXEL, STATUS, hold  # noqa: E402


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    away = lambda: (page.mouse.move(5, 5), page.wait_for_timeout(250))
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    rows = lambda: page.eval_on_selector_all("#history li", "els => els.map((e) => `${e.querySelector('.title').textContent}: ${e.querySelector('small').textContent}${e.classList.contains('hidden-above') ? ' (dimmed)' : ''}`)")
    passes = lambda: [m.group(1) for line in page.evaluate("window.__lines") for m in [re.match(r"Edit (\d): Paint ", line)] if m]
    p2, p3 = (0.47, 0.25), (0.78, 0.80)  # on the second edit's stroke, away from the first edit; on the third edit's stroke
    plate2, plate3 = pixel(p2), pixel(p3)

    # edit 2 starts on edit 1's stroke, so it depends on it; edit 3 is far from both
    page.keyboard.press("b")
    for words, pts in (("a red fire", [(0.15, 0.25), (0.25, 0.25)]), ("a blue vase", [(0.22, 0.25), (0.50, 0.25)]), ("a green lamp", [(0.70, 0.80), (0.85, 0.80)])):
        U.paint_once(page, words, pts); page.keyboard.press("n")
    page.wait_for_function(U.DONE.format(n=3), timeout=120000)

    # 1. Edit 1 changed, then Generate: edit 2 is generated again after it, edit 3 is not
    page.click("#history li:nth-child(3) .what"); away()
    U.stroke(page, [(0.10, 0.32), (0.14, 0.32)]); away()
    page.evaluate(U.WATCH)
    page.keyboard.press("Enter")
    again = U.until(page, U.added_line("Edit 2: Paint "), 30000)
    page.wait_for_function(U.DONE.format(n=3), timeout=120000)
    U.check(again and passes() == ["1", "2"], f"after edit 1 is made again, the edit above that depends on it is made again, and the edit far from it is not: passes of edits {passes()}")

    # 2. Edit 1 changed again, its first Klein pass held: edit 2 stays hidden until its own pass ends, edit 3 stays on the frame
    U.stroke(page, [(0.10, 0.18), (0.14, 0.18)]); away()
    hold(port, output="patch", seconds=8)
    page.evaluate(U.WATCH)
    page.keyboard.press("Enter")
    page.wait_for_function(f"{STATUS}.includes('first look')", timeout=30000); away()
    U.check(np.abs(pixel(p2) - plate2).max() <= 16 and np.abs(pixel(p3) - plate3).sum() > 40,
            f"while edit 1 is generated, edit 2 is hidden ({pixel(p2).tolist()} against the plate's {plate2.tolist()}) and edit 3 stays ({pixel(p3).tolist()} on {plate3.tolist()})")
    U.check(rows()[1] == "2. Paint: Waits to be generated again (dimmed)" and "dimmed" not in rows()[0], f"History says that edit 2 waits for its pass, and edit 3 does not: {rows()}")
    page.wait_for_function(U.added_line("Edit 2: Paint "), timeout=60000)
    page.wait_for_function(U.DONE.format(n=3), timeout=120000); page.keyboard.press("Escape"); away()
    U.check(np.abs(pixel(p2) - plate2).sum() > 40 and not any("dimmed" in r for r in rows()) and passes() == ["1", "2"],
            f"once its own pass has ended, edit 2 shows again: {pixel(p2).tolist()}; History {rows()}")
    page.close()
