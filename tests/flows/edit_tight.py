"""The edit workstream's check of the box the prompt writer gets for an erase with no words (tests/flows/README.md). On 12
November 2026 two of SAM's five masks for a stroke on a barn took in the horse's nose; with a box around them all, the
prompt writer removed the horse, the page refused, and the barn stayed. With the box cut to the stroke and to what most
masks agree on (logic.coreBox, writerBoxes), it removed the barn (the probe, 13 November). Here the mock's SAM takes
another object into two of its five masks, left of the stroke (/mock/snap), and the mock's writer removes that other
object when its box reaches it, the painted bottle otherwise (/mock/writer), as the laptop's writer did."""
import re

BOTTLE = ('Remove the red bottle <bottle_1> completely, with its shadow. [{"id": "bottle_1", "from": "ref_image_0", '
          '"src_bbox": [300, 530, 560, 700], "tgt_bbox": null, "desc": "a red bottle"}]')
HORSE = ('Remove the horse <horse_1> completely. [{"id": "horse_1", "from": "ref_image_0", '
         '"src_bbox": [80, 40, 300, 260], "tgt_bbox": null, "desc": "a brown horse"}]')
NOSE = [0.53, 0.42, 0.04, 0.05]  # another object, left of the stroke: its centre and radii, as fractions of the frame
EDGE = 530  # the writer removes the horse when a locked box starts left of this (0 to 1000)
ASKED = re.compile(r'prompt writer \(table mode\) for "no words" in box \[(\d+),(\d+),(\d+),(\d+)\]')


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    U.mock_route(port, "/mock/snap", {"times": 2, "extra": NOSE, "points": [0, 1]})
    U.mock_route(port, "/mock/writer", {"times": 3, "text": BOTTLE, "wide": {"x_min_below": EDGE, "text": HORSE}})
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])  # one stroke on the bottle, with no words
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "render of the erase")
    lines = page.evaluate("window.__lines")
    asked = [m for m in (ASKED.search(t) for t in lines) if m]
    U.check(bool(asked) and all(int(m[2]) >= EDGE for m in asked),
            f"the writer gets one box cut to the stroke and to what most masks agree on, without the other object ({[m[0] for m in asked]})")
    U.check(any("caption from the prompt writer: Remove the red bottle <bottle_1>" in t for t in lines)
            and not any("another object" in t for t in lines), "the writer names the painted object, and the page keeps its answer")
    U.check(any("Edit 1: the object left the first frame" in t for t in lines), "Klein removes it, and its shot renders")
    U.no_errors(errors, "after an erase with no words")
    page.close()
