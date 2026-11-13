"""The page workstream's check of an erase that leaves its object (tests/flows/README.md). Klein can answer an erase with
the frame as it was: on 12 November 2026 a stroke on a barn, with no words, left the barn in the whole shot, and nothing
said so. After the edit the page compares the first frame with the frame under it inside the object's mask. When the
object is still there, the status line says so and what to do next, the log says it once, History's row says it, and its
shot does not render. Once the object is named, Generate runs the erase again and its shot renders. The mock answers
the next edit jobs with the frame as it was (/mock/leave)."""

LEFT = "removed nothing: the object is still on the first frame"
NEXT = "Type its name in the prompt bar, then Generate."
ROW = """(() => { const li = document.querySelector('#history li');
  return li ? [li.className, li.dataset.left ?? '', li.querySelector('small').textContent] : null; })()"""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    U.mock_route(port, "/mock/leave", {"times": 2})  # the erase's quick pass and its full-size pass
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])  # one stroke on the bottle, with no words
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(LEFT), 90000, "line that says the object is still there")
    U.settled(page)
    status = page.text_content("#status")
    U.check(LEFT in status and status.endswith(NEXT), f"an erase that left its object: the status line says so, and what to do next ({status})")
    lines = page.evaluate("window.__lines")
    U.check(sum(LEFT in t for t in lines) == 1 and not any(NEXT in t for t in lines),
            "the log says it once, and what to do next stays in the status line")
    U.check(not any(t.startswith("Render v") or "is on the first frame" in t for t in lines), "its shot does not render")
    row = page.evaluate(ROW)
    U.check(bool(row) and "failed" in row[0] and row[1] == "1" and row[2] == "The object is still there",
            f"History's row says that the object is still there ({row})")
    page.fill("#prompt", "bottle"); page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "render of the erase once the object is named")
    lines, row = page.evaluate("window.__lines"), page.evaluate(ROW)
    U.check(any("Edit 1: the object left the first frame" in t for t in lines) and "failed" not in row[0] and row[1] == "",
            f"once the object is named, Generate runs the erase again: the object leaves the first frame, and its shot renders ({row})")
    U.no_errors(errors, "after an erase that left its object")
    page.close()
