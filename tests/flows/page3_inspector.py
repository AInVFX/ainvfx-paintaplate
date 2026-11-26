"""The colour inspector's average follows the step displayed: the points sampled with Shift held are read again from it,
as the point is. Two points sampled on the full-size composite; then another step displayed: the average row holds that
step's mean of the two points, which each point sampled alone on that step gives."""

AT = "([fx, fy]) => { const r = document.querySelector('#view').getBoundingClientRect(); return [r.left + fx * r.width, r.top + fy * r.height]; }"
BOX = "(() => { const i = document.querySelector('#inspector'); return [i.dataset.pixel, i.dataset.value, i.dataset.source, [...i.querySelectorAll('div')].map((d) => d.textContent)]; })()"
STEP = "Track the paint, preview"


def average(rows):
    """N and the three values under « Average source colour of N », or None."""
    i = next((k for k, r in enumerate(rows) if r.startswith("Average source colour of ")), None)
    if i is None:
        return None
    return int(rows[i].rsplit(" ", 1)[1]), [float(r[len(n):]) for r, n in zip(rows[i + 1:i + 4], ("Red", "Green", "Blue"))]


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 300000, "the full-size composite of the paint")
    U.settled(page)
    page.keyboard.press("n"); page.keyboard.press("Home")
    page.keyboard.press("F5")
    U.check(U.poll(page, lambda: page.is_visible("#inspector"), 5), "F5 shows the Colour Inspector")
    a, b = page.evaluate(AT, [0.31, 0.61]), page.evaluate(AT, [0.34, 0.64])

    page.keyboard.down("Shift"); page.mouse.move(*a); page.mouse.down()
    U.check(U.poll(page, lambda: page.evaluate(BOX)[1] != "", 20), "Shift+press samples the first point")
    pa = page.evaluate(BOX)[0]
    page.mouse.move(*b)
    U.check(U.poll(page, lambda: (average(page.evaluate(BOX)[3]) or [0])[0] == 2, 20),
            f"Shift+drag to a second pixel: « Average source colour of 2 »: {page.evaluate(BOX)[3]}")
    page.mouse.up(); page.keyboard.up("Shift")
    pb, before = page.evaluate(BOX)[0], average(page.evaluate(BOX)[3])[1]

    page.click(f"#stages li.pick:has-text('{STEP}')")
    U.check(U.poll(page, lambda: page.evaluate(BOX)[2] == STEP and average(page.evaluate(BOX)[3]) is not None, 20),
            f"another step displayed, the inspector reads it and keeps the average row: {page.evaluate(BOX)[2:]}")
    n, after = average(page.evaluate(BOX)[3])

    def alone(xy, pixel):  # Shift+click: one point, read from the step displayed
        page.keyboard.down("Shift"); page.mouse.click(*xy); page.keyboard.up("Shift")
        U.check(U.poll(page, lambda: page.evaluate(BOX)[0] == pixel and page.evaluate(BOX)[2] == STEP and page.evaluate(BOX)[1] != "", 20),
                f"Shift+click reads pixel {pixel} alone on {STEP}")
        return [float(v) for v in page.evaluate(BOX)[1].split(",")][:3]
    vb, va = alone(b, pb), alone(a, pa)  # b first: the box then sits below and right of b, away from a
    want = [(p + q) / 2 for p, q in zip(va, vb)]
    U.check(n == 2 and all(abs(g - w) < 2e-6 for g, w in zip(after, want)),
            f"the average follows the step displayed: {after} on {STEP}, the mean of its two points {want}")
    U.check(any(abs(g - w) > 1e-3 for g, w in zip(after, before)),
            f"the two steps differ at these points, so the check above proves something: {before} on the composite")
    page.close()
