"""A relight with no words (tests/flows/README.md). Its request is the page's own, written from the strokes
(logic.lightIntent): no prompt writer runs, and no line of the log or the status line names one. The stroke is a small light
inside the frame, so the request shows its source where it is drawn. Klein runs, and the shot renders."""
WRITER = "prompt writer"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="light"]')
    U.paint_once(page, "", [(0.3, 0.3), (0.34, 0.32)])  # one light stroke, with no words
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "render of the relight")
    lines = page.evaluate("window.__lines")
    U.check(any("relight request: " in t for t in lines), "the page writes the relight's request from its strokes")
    U.check(not any(WRITER in t for t in lines), f"no line names the prompt writer ({[t for t in lines if WRITER in t][:1]})")
    U.check(any("Klein edit preview" in t for t in lines), "Klein runs")
    asked = [t for t in lines if "relight request: " in t]
    U.check(bool(asked) and "<light_1>" in asked[-1] and '"tgt_bbox": [' in asked[-1],
            "a small light inside the frame shows its source: the request places it with a row of Klein's layout table")
    U.no_errors(errors, "after a relight with no words")
    page.close()
