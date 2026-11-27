"""A check of an erase with no text prompt that Klein's prompt writer takes for another object (tests/flows/README.md). The page
refuses an answer that removes an object outside the paint and asks the writer once more, on the frame with all but the
object dimmed. When that answer removes another object too, the page asks for the object's name before Klein runs: the
status line says so and what to do next, the log says it once, no Klein pass and no shot run, and History's row says that
the object is still there. Once the object is named, Generate runs the erase and its shot renders. The mock's prompt
writer answers the next two requests, the first look and the look at the dimmed frame, by removing a horse elsewhere
(/mock/writer)."""

ASK = "the prompt writer took the stroke for another object"
DIMMED = ", on the frame with all but the object dimmed."
NEXT = "Type its name in the text prompt, then press Enter."
HORSE = ('Remove the horse <horse_1> completely, including its bridle. [{"id": "horse_1", "from": "ref_image_0", '
         '"src_bbox": [80, 40, 300, 260], "tgt_bbox": null, "desc": "a brown horse"}]')
ROW = """(() => { const li = document.querySelector('#history li');
  return li ? [li.className, li.dataset.left ?? '', li.querySelector('small').textContent] : null; })()"""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    U.mock_route(port, "/mock/writer", {"times": 2, "text": HORSE})  # the first look, then the look at the dimmed frame
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])  # one stroke on the bottle, with no text prompt
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(ASK), 90000, "line that says the prompt writer took the stroke for another object")
    U.settled(page)
    status = page.text_content("#status")
    U.check(ASK in status and status.endswith(NEXT),
            f"an erase the writer took for another object: the status line asks for the object's name ({status})")
    lines = page.evaluate("window.__lines")
    asks = [t for t in lines if "asking Klein's prompt writer" in t]
    U.check(len(asks) == 2 and asks[1].endswith(DIMMED), f"the writer looks twice, the second time at the dimmed frame ({asks})")
    U.check(sum(ASK in t for t in lines) == 1 and not any(NEXT in t for t in lines),
            "the log says it once, and what to do next stays in the status line")
    U.check(not any("Klein edit preview" in t or t.startswith("Render v") for t in lines),
            "no Klein pass runs and no shot renders")
    row = page.evaluate(ROW)
    U.check(bool(row) and "failed" in row[0] and (row[1] == "1" or row[2].startswith("Needs its name")),
            f"History's row says that the edit needs the object's name, or that the object is still there ({row})")
    page.fill("#prompt", "bottle"); page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "render of the erase once the object is named")
    lines, row = page.evaluate("window.__lines"), page.evaluate(ROW)
    U.check(any("Klein edit preview" in t for t in lines) and "failed" not in row[0] and row[1] == "",
            f"once the object is named, Generate runs Klein and the shot renders ({row})")
    U.no_errors(errors, "after an erase that the writer took for another object")
    page.close()
