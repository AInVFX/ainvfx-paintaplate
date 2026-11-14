"""A check of an erase with no words whose prompt writer names another object than the one under the stroke
(tests/flows/README.md). The page refuses that answer and asks the writer once more, with the same box, on the frame with
all but the object dimmed; that answer removes the object under the stroke. Klein runs, the shot renders, and the page
never asks for the object's name. The mock's prompt writer answers the first request by removing a barn elsewhere
(/mock/writer), and the next one with the request itself, which removes the object in the box."""
import json
import re

BARN = ('Remove the barn <barn_1> completely, including its roof. [{"id": "barn_1", "from": "ref_image_0", '
        '"src_bbox": [80, 40, 300, 260], "tgt_bbox": null, "desc": "a grey barn"}]')
REFUSED = "prompt writer's answer refused: it removes an object outside the paint"
ASKING = "asking Klein's prompt writer"
DIMMED = ", on the frame with all but the object dimmed."
ASK = "the prompt writer took the stroke for another object"
BOX = re.compile(r'for "no words" in box (\[[0-9,]+\])')
ROW = """(() => { const li = document.querySelector('#history li');
  return li ? [li.className, li.dataset.left ?? ''] : null; })()"""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    U.mock_route(port, "/mock/writer", {"times": 1, "text": BARN})
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])  # one stroke on the bottle, with no words
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "render of the erase once the writer looked at the dimmed frame")
    lines, row = page.evaluate("window.__lines"), page.evaluate(ROW)
    asks = [t for t in lines if ASKING in t]
    boxes = [json.loads(m.group(1)) for m in (BOX.search(t) for t in asks) if m]
    U.check(sum(REFUSED in t for t in lines) == 1, "the writer's answer about the barn is refused once")
    U.check(all(t.startswith("Edit 1: ") for t in asks) and not any(t.startswith("Edit New") for t in lines),
            f"the draft's lines carry the number it takes in History ({asks[:1]})")
    U.check(len(asks) == 2 and not asks[0].endswith(DIMMED) and asks[1].endswith(DIMMED) and len(boxes) == 2 and boxes[0] == boxes[1],
            f"the writer looks once more, with the same box, at the dimmed frame ({asks})")
    U.check(not any("SAM 3.1 looking for the barn" in t for t in lines), "no SAM job looks for the barn")
    U.check(not any(ASK in t for t in lines) and any("Klein edit preview" in t for t in lines),
            "the page does not ask for the object's name: Klein runs")
    U.check(bool(row) and "failed" not in row[0] and row[1] == "", f"History's row is not marked ({row})")
    U.no_errors(errors, "after an erase whose writer named another object")
    page.close()
