"""Edits are layers. While an edit of History is changed, the first frame shows the edits under it and its strokes: its
own old result and every edit above it are hidden, History dims their rows and the status line says so. After Generate
the edits above show again."""
import pathlib
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
    status = lambda: page.text_content("#status")
    away = lambda: (page.mouse.move(5, 5), page.wait_for_timeout(250))
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    hidden = lambda: page.eval_on_selector_all("#history li.hidden-above", "els => els.map((e) => `${e.querySelector('.title').textContent}: ${e.querySelector('small').textContent}`)")
    p1, p3 = (0.25, 0.30), (0.75, 0.70)  # inside the first and the third edit's stroke
    plate1, plate3 = pixel(p1), pixel(p3)

    # three paint edits far from each other, so none depends on another
    page.keyboard.press("p")
    for words, x, y in (("a red fire", 0.20, 0.30), ("a blue vase", 0.45, 0.50), ("a green lamp", 0.70, 0.70)):
        U.paint_once(page, words, [(x, y), (x + 0.10, y)]); page.keyboard.press("n")
    page.wait_for_function(U.DONE.format(n=3), timeout=120000)

    # 1. The second edit selected, nothing changed yet: every edit shows
    page.click("#history li:nth-child(2) .what"); away()
    shown1, shown3 = pixel(p1), pixel(p3)
    U.check(page.text_content("#editing").startswith("Editing 2") and np.abs(shown1 - plate1).sum() > 40 and np.abs(shown3 - plate3).sum() > 40 and not hidden(),
            f"an edit selected and not changed hides nothing: edit 1 shows {shown1.tolist()} on a plate of {plate1.tolist()}, edit 3 {shown3.tolist()} on {plate3.tolist()}")

    # 2. The second edit changed, by a rub: the edit above it is hidden, the edit under it stays
    page.keyboard.press("x"); U.stroke(page, [(0.52, 0.50), (0.58, 0.50)]); page.keyboard.press("x"); away()
    U.check(np.abs(pixel(p3) - plate3).max() <= 16,
            f"while edit 2 is changed, the frame shows the plate where only edit 3 painted: {pixel(p3).tolist()} against the plate's {plate3.tolist()}")
    U.check(np.abs(pixel(p1) - shown1).max() <= 16, f"the edit under it stays on the frame: {pixel(p1).tolist()}, as before ({shown1.tolist()})")
    U.check(U.until(page, f"{STATUS} === 'Edit 2 is being changed: edit 3 is hidden until it is generated.'", 3000),
            f"the status line names the hidden edit: {status()}")
    U.check(hidden() == ["3. Paint: Hidden until edit 2 is generated"], f"History dims the hidden row and says why: {hidden()}")

    # 3. Generate: the edit above shows again. The first LTX pass is held, so the frame shows the edits, not a new shot
    hold(port, slot="live", seconds=40)
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=3), timeout=120000); away()
    U.check(np.abs(pixel(p3) - plate3).sum() > 40 and not hidden(), f"after Generate, edit 3 shows again: {pixel(p3).tolist()}")
    page.close()
