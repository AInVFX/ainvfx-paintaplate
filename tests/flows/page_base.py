"""The check of the first frame under a new edit (tests/flows/README.md). A Clean and a Paint are made
and rendered on desk.mp4. A new edit shows the first frame as the edits below it made it: started by a tool, by a stroke
on a later frame (the viewer goes back to the first frame, and the status line's note says why), after a click on a
History row (the row shows that edit and selects nothing) and with Preview size: Off. The row's pencil selects an older
edit: the log names it, and while it changes the edit above it hides, which the status line's note names. An undo ends
the selection."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from viewer_edit import OPEN, PIXEL  # noqa: E402

E1, E2, E3 = [(0.18, 0.35), (0.26, 0.45)], [(0.62, 0.35), (0.70, 0.45)], [(0.45, 0.72), (0.52, 0.78)]  # Clean, Paint, the new edit
P1, P2 = (0.22, 0.40), (0.66, 0.40)  # inside the Clean's and the Paint's strokes
NOTE = "(() => { const n = document.querySelector('#status-note'); return n.hidden ? '' : n.textContent; })()"


def run(browser, port, U):
    page = U.load(browser, port, "?blank=0&seed=5")  # a fixed seed: the mock makes the same pictures in every run
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))  # noqa: E731
    away = lambda: (page.mouse.move(5, 5), page.wait_for_timeout(250))  # noqa: E731
    note = lambda: page.evaluate(NOTE)  # noqa: E731
    hidden = lambda: page.eval_on_selector_all("#history li.hidden-above", "els => els.map((e) => e.querySelector('.title').textContent)")  # noqa: E731

    def tool(name):  # a tool picked by its button
        page.click(f'.tools [data-tool="{name}"]')
        page.evaluate("document.activeElement.blur()")
    plate1, plate2 = pixel(P1), pixel(P2)

    def both():  # the first frame shows the Clean's and the Paint's results
        s1, s2 = pixel(P1), pixel(P2)
        return np.abs(s1 - plate1).sum() > 40 and np.abs(s2 - plate2).sum() > 40, f"{s1.tolist()} on {plate1.tolist()}, {s2.tolist()} on {plate2.tolist()}"

    tool("erase"); U.paint_once(page, "lamp", E1); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000); U.settled(page)
    tool("paint"); U.paint_once(page, "a red ball", E2); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000); U.settled(page)
    U.check(U.row_titles(page) == ["2. Paint", "1. Clean"], f"a Clean, then a Paint: {U.row_titles(page)} {U.row_words(page)}")

    tool("erase"); U.stroke(page, E3); away()
    ok, seen = both()
    U.check(ok and page.is_hidden("#editing"), f"a new edit started by a tool shows the first frame as the edits below it made it: {seen}, status {page.text_content('#status')!r}")
    page.keyboard.press("Escape")

    box = page.eval_on_selector("#timeline", "e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
    page.mouse.click(box[0] + box[2] * 0.6, box[1] + box[3] / 2)
    U.until(page, "document.querySelector('#frame-now').textContent !== '1'", 5000)
    later = page.text_content("#frame-now")
    U.stroke(page, E3); away()
    ok, seen = both()
    U.check(later != "1" and page.text_content("#frame-now") == "1" and note() == "Edits are painted on the first frame." and ok,
            f"a stroke on frame {later} lands on the first frame, which shows both results, and the status line's note says so: frame {page.text_content('#frame-now')}, note {note()!r}, {seen}")
    page.keyboard.press("Escape")
    U.check(note() == "", f"Esc ends the note with the edit: {note()!r}")

    page.click("#history li:last-child .what"); away()
    row = page.get_attribute("#history li:last-child", "class") or ""
    U.check("shown" in row.split() and "selected" not in row.split() and page.is_hidden("#editing") and page.input_value("#prompt") == "",
            f"a click on Edit 1's row shows it and selects nothing: class {row!r}, prompt {page.input_value('#prompt')!r}")
    start = len(U.log_lines(page))
    U.stroke(page, E3); away()
    for _ in range(80):  # the new edit's first line, once the stroke rests: it carries the number the edit takes in History, above the two edits
        added = U.log_lines(page)[start:]
        if any(t.startswith("Edit 3:") for t in added):
            break
        page.wait_for_timeout(250)
    ok, seen = both()
    U.check(ok and page.is_hidden("#editing") and not hidden() and any(t.startswith("Edit 3:") for t in added) and not any(t.startswith("Edit 1:") for t in added),
            f"after the click, a stroke of Edit 1's tool starts a new edit on top: {seen}, lines {[t[:40] for t in added[:3]]}")
    page.keyboard.press("Escape")

    start = len(U.log_lines(page))
    page.click("#history li:last-child .edit"); away()
    U.check(page.text_content("#editing") == "Editing 1 · Clean" and "Edit 1 selected." in U.log_lines(page)[start:],
            f"the pencil selects Edit 1 and the log names it: {page.text_content('#editing')!r}")
    U.stroke(page, E3); away()
    U.until(page, f"{NOTE}.startsWith('Edit 1 changes')", 5000)
    s2 = pixel(P2)
    U.check(note() == "Edit 1 changes: Edit 2 hides until Generate. Esc cancels the change." and hidden() == ["2. Paint"] and np.abs(s2 - plate2).max() <= 16,
            f"while Edit 1 changes, Edit 2 hides and the status line's note names it: {note()!r}, rows {hidden()}, {s2.tolist()} on {plate2.tolist()}")
    page.keyboard.press("Control+z"); away()
    U.check(page.is_hidden("#editing") and note() == "" and not hidden(), f"an undo ends the selection and the note: {note()!r}, rows {hidden()}")

    page.select_option("#preview-size", value="latent")
    tool("erase"); U.stroke(page, E3); away()
    ok, seen = both()
    U.check(ok and page.is_hidden("#editing"), f"with no preview pass, a new edit shows the same first frame: {seen}")
    page.keyboard.press("Escape")
    page.close()
