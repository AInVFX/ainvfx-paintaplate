"""A check of an erase that took more than its object (tests/flows/README.md). After the edit, the page also compares the
first frame with the frame under it in the band that the edit reaches beyond the object's mask (logic.eraseCheck,
bandBeyond). When over 20% of that band changed, as when Klein removes a fence with the barn behind it, the page asks in its
question dialog, with History's row marked in the question's words. « Yes, render anyway » keeps the first frame and renders its
shot. The mock's Klein reaches far beyond the object for the next erase (/mock/spill)."""
import re

FACT = "Warning: edit 1, the erase also changed the area around the object ("  # the log's line
ASKS = "Edit 1: the erase also changed the area around the object ("  # the dialog's question
QUESTION = ". Render the shot anyway?"
ANYWAY = "Edit 1: kept at your request. The check found the area around the object changed."
FIGURE = re.compile(r"\((\d+)% of that area changed")
ROW = """(() => { const li = document.querySelector('#history li');
  return li ? [li.className, li.dataset.left ?? '', li.querySelector('small').textContent] : null; })()"""
ASKED = """(() => { const d = document.querySelector('#ask');
  return d.open ? [d.querySelector('#ask-text').textContent, d.querySelector('#ask-yes').textContent] : null; })()"""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    U.mock_route(port, "/mock/spill", {"times": 2})  # the erase's edit preview and its full-size pass
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])  # one stroke on the bottle, with no text prompt
    page.keyboard.press("Enter")
    page.wait_for_selector("#ask[open]", timeout=90000)
    asked, row, lines = page.evaluate(ASKED), page.evaluate(ROW), page.evaluate("window.__lines")
    figure = FIGURE.search(asked[0]) if asked else None
    U.check(bool(asked) and asked[0].startswith(ASKS) and asked[0].endswith(QUESTION) and asked[1] == "Yes, render anyway"
            and bool(figure) and int(figure.group(1)) > 20, f"the page asks about the area around the object, over 20% of it changed ({asked})")
    U.check(bool(row) and "failed" in row[0] and row[1] == "1" and row[2] == "The area around the object changed",
            f"History's row is marked, in the question's words ({row})")
    U.check(sum(t.startswith(FACT) for t in lines) == 1 and not any(t.startswith("Warning: edit 1, the object may still be there") for t in lines),
            "the log says the warning once, and not as an object that stayed")
    page.click("#ask-yes")
    page.wait_for_function("(t) => window.__lines.some((l) => l.includes(t))", arg=ANYWAY, timeout=60000)
    U.wait_log(page, U.added_line("Render v1"), 120000, "render v1 after Render anyway")
    row = page.evaluate(ROW)
    U.check(page.is_hidden("#ask") and "failed" not in row[0] and row[1] == "", f"Render anyway keeps the frame, the shot renders, and the mark goes ({row})")
    U.no_errors(errors, "after an erase that changed the area around its object")
    page.close()
