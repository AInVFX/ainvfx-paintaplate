"""The laptop's session for P8 and autoplay, end to end, with autoplay on as a person has it: a fluid shot with two
keyframes, then a Paint edit on it; each step's result plays as it is made and the text prompt field empties after each
Generate; the Paint edit's pencil shows its strokes over the picture it paints on; Esc plays the latest result; the fluid
shot's pencil goes to its nearest keyframe on the black plate; the fluid shot made again shows no old result while it
renders; a keyframe dragged selects the fluid shot, and Enter makes it again on its seed."""
import pathlib
import re
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import PIXEL  # noqa: E402

ROW = "#history li:has(.title:text-is('{}'))"
WATCH = """window.__status = []; for (const id of ['#status', '#hud']) new MutationObserver(() => window.__status.push(document.querySelector(id).textContent))
  .observe(document.querySelector(id), { childList: true, subtree: true, characterData: true });"""  # the status line and the HUD, each text they show
LOG = "[...document.querySelectorAll('#log li')].map((e) => e.textContent)"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors, autoplay=True)
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    frame = lambda: int(page.text_content("#frame-now"))
    playing = lambda: page.evaluate("document.querySelector('#play-btn').classList.contains('playing')")
    said = lambda part: any(part in t for t in page.evaluate("window.__status"))
    empty = lambda: page.input_value("#prompt") == "" and page.is_hidden("#editing")

    def go(n):  # the plate's frame n, with the arrow keys (they pause), the pointer off History
        page.mouse.move(5, 5)
        page.keyboard.press("Home")
        for _ in range(n - frame()):
            page.keyboard.press("ArrowRight")
        U.poll(page, lambda: frame() == n, 5)
        page.wait_for_timeout(300)

    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.evaluate(WATCH)
    U.check(page.text_content("#status").endswith("then press Enter.") and page.text_content("#fluid .hint").endswith("then press Enter."),
            f"the blank plate's lines are this build's: {page.text_content('#status')!r}")

    # 1. A fluid shot with two keyframes: each step plays as it is made, and the field empties
    U.paint_once(page, "green smoke", [(0.25, 0.72), (0.3, 0.7), (0.35, 0.72)])
    go(17); U.stroke(page, [(0.65, 0.32), (0.7, 0.3), (0.75, 0.32)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    U.settled(page)
    U.check(said("Fluid shot, preview: playing.") and said("Fluid shot, full size: playing.") and playing() and empty(),
            f"the fluid shot's preview, then its full size, play as they are made, and the field is empty: playing {playing()}, field {page.input_value('#prompt')!r}")

    # 2. A Paint edit on it: its steps play as they are made, and the field empties after Enter
    page.click('.tools [data-tool="paint"]')
    robot = (0.5, 0.5)
    U.paint_once(page, "a giant robot", [(0.45, 0.5), (0.55, 0.5)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)
    U.check(said("Composite, full size: playing.") and playing() and empty(),
            f"the Paint edit's composite plays as it is made, and the field is empty: line {said('Composite, full size: playing.')}, playing {playing()}, field {page.input_value('#prompt')!r}, chip hidden {page.is_hidden('#editing')}")
    page.keyboard.press("Space"); page.keyboard.press("Home"); page.mouse.move(5, 5); page.wait_for_timeout(600)
    composite = pixel(robot)
    page.keyboard.press("Space")

    # 3. The Paint edit's pencil: playback stops on frame 1, its strokes at full strength over the fluid shot's first frame
    page.click(ROW.format("2. Paint") + " .edit"); page.mouse.move(5, 5); page.wait_for_timeout(400)
    color = page.input_value("#color"); paint = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)])
    U.check(not playing() and frame() == 1 and page.text_content("#editing") == "Editing 2 · Paint" and page.input_value("#prompt") == "a giant robot"
            and np.abs(pixel(robot) - paint).sum() <= 30,
            f"the pencil stops playback on frame {frame()}, the chip reads {page.text_content('#editing')!r}, its words come back, its strokes show in {color}: {pixel(robot).tolist()}")

    # 4. Esc: deselected, the latest result plays
    page.keyboard.press("Escape")
    U.check(U.poll(page, playing, 5) and empty(), "Esc deselects the edit, and the latest result plays")

    # 5. From frame 14, the fluid shot's pencil: its keyframe on frame 18, on the black plate
    go(14)
    page.click(ROW.format("1. Fluid") + " .edit"); page.mouse.move(5, 5); page.wait_for_timeout(400)
    U.check(frame() == 18 and page.text_content("#editing") == "Editing 1 · Fluid" and pixel((0.7, 0.3)).min() > 150 and pixel((0.5, 0.75)).max() < 20,
            f"the fluid shot's pencil goes from frame 14 to its keyframe on frame {frame()}, on the black plate, chip {page.text_content('#editing')!r}")

    # 6. The fluid shot made again: while it renders, no old result shows, and the Paint row waits
    U.stroke(page, [(0.6, 0.35), (0.65, 0.37)])
    U.mock_route(port, "/mock/hold", {"output": "plate", "seconds": 8, "times": 1})
    page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: any(e[0] == "held" for e in U.mock_route(port, "/mock/events")), 60), "the fluid shot renders again, its first step held open")
    go(1)
    meanwhile, small = pixel(robot), page.text_content(ROW.format("2. Paint") + " small")
    U.check(np.abs(meanwhile - composite).sum() > 40 and small == "Waits for the fluid shot",
            f"meanwhile frame 1 shows no old robot ({meanwhile.tolist()} where the composite had {composite.tolist()}), and the Paint row reads {small!r}")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)

    # 7. The second keyframe dragged to frame 26: the fluid shot is selected; Enter makes it again on its seed
    seeds = lambda: [m.group(1) for t in page.evaluate(LOG) for m in [re.search(r"Fluid 1\), seed (\d+)", t)] if m]
    before = seeds()
    diamond = page.locator("#tl-keys .tl-kf").nth(1)
    box, line = diamond.bounding_box(), page.locator("#timeline").bounding_box()
    x0, y0, to = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, line["x"] + (25.5 / 33) * line["width"]
    page.mouse.move(x0, y0); page.mouse.down()
    for k in range(1, 6):
        page.mouse.move(x0 + (to - x0) * k / 5, y0)
    page.mouse.up(); page.mouse.move(5, 5)
    U.check(U.poll(page, lambda: page.is_visible("#editing") and page.text_content("#editing") == "Editing 1 · Fluid", 5), "the dragged keyframe selects the fluid shot")
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)
    after = seeds()
    U.check(len(after) > len(before) and after[-1] == before[-1], f"Enter makes the fluid shot again, on its seed: {before} then {after}")
    U.no_errors(errors, "in the session")
    page.close()
