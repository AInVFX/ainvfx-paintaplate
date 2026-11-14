"""The edit workstream's check of an erase with no words whose prompt writer names another object than the one under the
stroke (tests/flows/README.md). SAM 3.1 finds that object by the writer's name for it, the writer's box leaves it out, and
the writer, asked again, removes the object under the stroke: Klein runs, the shot renders, and the page never asks for the
object's name. The mock's prompt writer answers the first request by removing a barn elsewhere (/mock/writer); its SAM 3.1
finds the barn by name across the lower part of the object's box (/mock/named)."""
import json
import re

BARN = ('Remove the barn <barn_1> completely, including its roof. [{"id": "barn_1", "from": "ref_image_0", '
        '"src_bbox": [80, 40, 300, 260], "tgt_bbox": null, "desc": "a grey barn"}]')
REFUSED = "prompt writer's answer refused: it removes an object outside the paint"
LEFT_OUT = "the barn left out of the prompt writer's box"
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
    U.mock_route(port, "/mock/named", {"times": 1, "ellipse": [0.61, 0.56, 0.15, 0.06]})
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])  # one stroke on the bottle, with no words
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "render of the erase once the barn is out of the writer's box")
    lines, row = page.evaluate("window.__lines"), page.evaluate(ROW)
    boxes = [json.loads(m.group(1)) for m in (BOX.search(t) for t in lines) if m]
    U.check(sum(REFUSED in t for t in lines) == 1 and sum(LEFT_OUT in t for t in lines) == 1,
            "the writer's answer about the barn is refused once, and the barn leaves the writer's box")
    U.check(len(boxes) == 2 and boxes[1][0] == boxes[0][0] and boxes[1][2] < boxes[0][2],
            f"the writer is asked again with the box above the barn ({boxes})")
    U.check(not any(ASK in t for t in lines) and any("Klein edit preview" in t for t in lines),
            "the page does not ask for the object's name: Klein runs")
    U.check(bool(row) and "failed" not in row[0] and row[1] == "", f"History's row is not marked ({row})")
    U.no_errors(errors, "after an erase whose writer named another object")
    page.close()
