"""A paint whose words name no colour (tests/flows/README.md): the page reads the colours that its strokes show and names
them in its request to Klein's prompt writer, largest share first. The mock's prompt writer answers with the request
itself, so the caption in the log holds what the page asked."""
RED, BLACK = '.sw[data-color="#d32f2f"]', '.sw[data-color="#000000"]'
NAMED = "with saddle in the drawing's colours, red and black: follow the drawing's outline"
ASKED = "for \"saddle\" in the drawing's colours, red and black, in box"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="paint"]')
    page.click(RED)
    U.paint_once(page, "saddle", [(0.3, 0.5), (0.7, 0.52)])  # a long red stroke
    page.click(BLACK)
    U.paint_once(page, "saddle", [(0.45, 0.5), (0.52, 0.51)])  # a short black one over it
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "render of the paint")
    lines = page.evaluate("window.__lines")
    asks = [t for t in lines if "asking Klein's prompt writer" in t]
    caps = [t for t in lines if t.startswith("Edit 1: caption from the prompt writer")]
    U.check(bool(asks) and ASKED in asks[-1], f"the last request names both colours ({asks[-1:]})")
    U.check(bool(caps) and NAMED in caps[-1], "the caption that Klein gets names the strokes' colours, largest share first")
    U.no_errors(errors, "after a paint whose words name no colour")
    page.close()
