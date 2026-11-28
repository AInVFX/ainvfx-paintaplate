"""The pipette on a stroke takes the colour the stroke was painted with, at its middle, along it and at its soft edge (app.
strokeColour): the draft's stroke, then the edit's once Klein made it and its History row shows its strokes, where the
picture under the stroke is Klein's."""
H = 704  # desk.mp4: 1280 x 704; the brush is 48 of its pixels across


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.keyboard.press("p")
    colour = next(c for c in page.eval_on_selector_all(".swatches .sw[data-color]", "(s) => s.map((b) => b.dataset.color)") if c.lower() not in ("#000000", "#ffffff"))
    page.click(f".sw[data-color='{colour}']")
    page.fill("#prompt", "a green ribbon"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.3, 0.5), (0.4, 0.5), (0.5, 0.5)])
    box = U.view_box(page)

    def pick(fx, fy):
        page.click("#pick")
        page.mouse.click(box["x"] + fx * box["w"], box["y"] + fy * box["h"])
        return page.input_value("#color").lower()

    edge = 0.5 + 22 / H  # inside the stroke's soft rim, 2 pixels from its outer edge
    got = [pick(0.4, 0.5), pick(0.33, 0.5), pick(0.45, edge)]
    U.check(got == [colour.lower()] * 3, f"the draft's stroke at its middle, along it and at its edge: {got}, painted {colour}")
    page.click(f".sw[data-color='{colour}']")
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Edit 1: done in"), 120000, "the edit")
    U.settled(page)
    page.click("#history li")  # its row shows its strokes, over Klein's picture
    got = [pick(0.4, 0.5), pick(0.45, edge)]
    U.check(got == [colour.lower()] * 2, f"the edit's stroke, over Klein's picture: {got}, painted {colour}")
    page.close()
