"""A keyframe dragged along the timeline while the fluid shot is not selected: the fluid shot is selected, as its pencil
selects it, and the moved keyframe shows; Enter then makes the fluid shot again, on its own seed."""
import re

FLUID = '#history li[data-id="fluid"]'
LOG = "[...document.querySelectorAll('#log li')].map((e) => e.textContent)"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    lines = lambda: page.evaluate(LOG)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.25, 0.72), (0.3, 0.7), (0.35, 0.72)])
    page.keyboard.press("Home")
    for _ in range(16):
        page.keyboard.press("ArrowRight")
    U.stroke(page, [(0.65, 0.32), (0.7, 0.3), (0.75, 0.32)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    U.settled(page)
    U.check(page.is_hidden("#editing"), "after Generate the fluid shot is not selected")
    seeds = lambda: [m.group(1) for t in lines() for m in [re.search(r"Render v\d+: 1 edit \(Fluid 1\), seed (\d+)", t)] if m]

    # Drag the second keyframe's diamond to the slot of frame 25
    diamond = page.locator("#tl-keys .tl-kf").nth(1)
    box, line = diamond.bounding_box(), page.locator("#timeline").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); page.mouse.down()
    to = line["x"] + (25.5 / 33) * line["width"]
    for k in range(1, 6):
        page.mouse.move(box["x"] + box["width"] / 2 + (to - box["x"] - box["width"] / 2) * k / 5, box["y"] + box["height"] / 2)
    page.mouse.up(); page.mouse.move(5, 5)
    U.check(U.poll(page, lambda: page.is_visible("#editing") and page.text_content("#editing") == "Editing 1 · Fluid", 5),
            f"a dragged keyframe selects the fluid shot: the chip reads {page.text_content('#editing')!r}")

    # Enter: the fluid shot is made again, on the same seed
    made = len([t for t in lines() if "Fluid shot v" in t and "started" in t])
    page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: len([t for t in lines() if "Fluid shot v" in t and "started" in t]) > made, 30), "Enter makes the fluid shot again")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.settled(page)
    s = seeds()
    U.check(len(s) >= 2 and s[-1] == s[0], f"on its own seed: {s}")
    U.no_errors(errors, "after the drag")
    page.close()
