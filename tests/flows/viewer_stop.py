"""A stop stops everything. After Esc on the edit being generated, no job is posted until Enter: an edit that waited for
its turn stays queued, a stroke asks for nothing, and Enter runs the stopped edit with its own words, then what waited.
Then: once SAM has found the object under an erase stroke, the status line says so."""
import json
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import OPEN, STATUS, hold  # noqa: E402


def posts(port):  # how many jobs the page has posted to the mock ComfyUI
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/mock/posts", timeout=5) as r:
        return len(json.loads(r.read()))


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    status = lambda: page.text_content("#status")
    states = lambda: page.eval_on_selector_all("#history li .state", "els => els.map((e) => e.textContent)")

    # 1. The first Klein pass of edit 1 is held, edit 2 waits for its turn, then Esc: nothing is posted
    hold(port, output="patch", seconds=30)
    page.keyboard.press("b"); U.paint_once(page, "a green lamp", [(0.20, 0.75), (0.30, 0.75)]); page.keyboard.press("Enter")
    page.wait_for_function(f"{STATUS}.includes('first look')", timeout=30000)
    page.keyboard.press("n"); U.paint_once(page, "a white cup", [(0.45, 0.20), (0.55, 0.20)]); page.keyboard.press("n")
    page.wait_for_function("document.querySelectorAll('#history li').length === 2", timeout=10000)
    page.wait_for_timeout(1500)  # what edit 2 asked for as its strokes rested is posted by now
    before = posts(port)
    page.keyboard.press("Escape"); page.wait_for_timeout(3000)
    U.check(posts(port) == before, f"for 3 s after Esc on the edit being generated no job is posted: {posts(port) - before} more than the {before} before")
    U.check(status().startswith("Stopped. Edit 1 keeps") and "Edit 2 waits." in status() and not page.is_disabled("#generate"),
            f"the status line names the edit that keeps its strokes and the edit that waits: {status()}")
    U.check(states() == ["Waits for Enter", "Drawing"] and page.input_value("#prompt") == "a green lamp" and page.text_content("#editing").startswith("Editing 1"),
            f"History says what waits ({states()}), and the stopped edit is the current edit with its own words in the prompt bar ({page.input_value('#prompt')!r})")

    # 2. A stroke on the stopped edit asks for nothing: SAM and the prompt writer wait for Enter too
    U.stroke(page, [(0.22, 0.80), (0.28, 0.80)]); page.wait_for_timeout(1500)
    U.check(posts(port) == before, f"a stroke painted after the stop posts no job: {posts(port) - before} more")

    # 3. Enter: the stopped edit runs with its own words, then the edit that waited
    page.evaluate(U.WATCH)
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    order = [m.group(1) for line in page.evaluate("window.__lines") for m in [re.match(r"Edit (\d): Paint ", line)] if m]
    U.check(order == ["1", "2"] and U.row_words(page) == ["a white cup", "a green lamp"],
            f"Enter runs the stopped edit, then the edit that waited, each with its own words: order {order}, History {U.row_words(page)}")

    # 4. SAM finds the object under an erase stroke: the status line says so, and no longer says it is looking
    page.keyboard.press("n"); page.keyboard.press("e")
    if not page.is_checked("#whole"):
        page.check("#whole")
    U.paint_once(page, "cup", [(0.6, 0.4), (0.62, 0.45)])
    U.check(U.until(page, f"{STATUS}.startsWith('Found the cup under the stroke')", 30000), f"once SAM's masks are kept the status line says the object is found: {status()}")
    page.close()
