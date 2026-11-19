"""The check of the tools' names and keys, and of the eraser's key (tests/flows/README.md). P, C and L
pick Paint, Clean and Light, and B and W are free. A tap on E switches the eraser on or off. E held with no stroke
leaves it as it was. E held while a stroke is dragged rubs the stroke out, and the eraser is off again when E comes up.
X toggles the X-ray, and Shift+E stays the exposure."""

PIXEL = """([fx, fy]) => { const c = document.querySelector('#view'), s = [0, 0, 0];
  const d = c.getContext('2d').getImageData(Math.round(c.width * fx) - 2, Math.round(c.height * fy) - 2, 5, 5).data;
  for (let i = 0; i < d.length; i += 4) for (let k = 0; k < 3; k++) s[k] += d[i + k] / 25; return s; }"""
OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    on = lambda tool: "on" in (page.get_attribute(f"[data-tool={tool}]", "class") or "").split()  # noqa: E731
    rub = lambda: page.get_attribute("#rub-btn", "aria-pressed") == "true"  # noqa: E731

    title = page.get_attribute("[data-tool=erase]", "title")
    U.check(page.text_content("[data-tool=erase] span") == "Clean" and title.startswith("Clean: remove an object") and title.endswith("(C)."),
            f"the tool that removes an object is named Clean, and its tooltip gives the key C: {title!r}")
    paint = page.get_attribute("[data-tool=paint]", "title")
    U.check(paint.endswith("(P)."), f"the Paint tooltip gives the key P: {paint!r}")
    page.keyboard.press("c")
    U.check(on("erase"), "C picks Clean")
    for key in ("b", "j"):  # T opens Text prompt…, S Colours…
        page.keyboard.press(key)
        U.check(on("erase") and not on("paint") and not rub() and page.is_hidden("#xray"),
                f"{key.upper()} is free: Clean stays picked, the eraser stays off and the X-ray stays hidden")
    page.keyboard.press("l")
    U.check(on("light"), "L picks Light")
    page.keyboard.press("p")
    U.check(on("paint") and not on("light"), "P picks Paint")

    page.keyboard.press("e")
    U.check(rub(), "a tap on E switches the eraser on")
    page.keyboard.press("e")
    U.check(not rub(), "a second tap switches it off")
    page.keyboard.down("e")
    U.check(rub(), "E held: the eraser is on while the key is down")
    page.wait_for_timeout(500)
    page.keyboard.up("e")
    U.check(not rub(), "E held for 0.5 s with no stroke: the eraser is off again, as before the press")

    at = [0.33, 0.50]  # the middle of the stroke
    pixel = lambda: page.evaluate(PIXEL, at)  # noqa: E731
    apart = lambda a, b: max(abs(x - y) for x, y in zip(a, b))  # noqa: E731
    plate = pixel()
    page.click(".sw[data-color='#d32f2f']")
    U.paint_once(page, "a lantern", [(0.30, 0.50), (0.36, 0.50)])
    page.evaluate("document.activeElement.blur()")
    page.mouse.move(2, 2)
    U.check(apart(pixel(), plate) > 40, f"the red stroke shows on the frame: {pixel()} on a plate of {plate}")
    for _ in range(6):
        page.keyboard.press("=")
    page.keyboard.down("e")
    U.stroke(page, [(0.27, 0.50), (0.39, 0.50)])
    page.keyboard.up("e")
    page.mouse.move(2, 2)
    U.check(not rub(), "E comes up after a stroke: the eraser is off again")
    U.check(U.poll(page, lambda: apart(pixel(), plate) <= 16, 5),
            f"the stroke dragged while E was held rubbed the paint out: {pixel()} against the plate's {plate}")
    page.close()
