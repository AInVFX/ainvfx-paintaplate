"""A stop stops everything. After Esc on the edit being generated, no job is posted until Enter: an edit that waited for
its turn stays queued, a stroke asks for nothing, and Enter runs the stopped edit with its own words, then what waited.
Then: once SAM has found the object under an erase stroke, the status line says so."""
import json
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from viewer_edit import OPEN, STATUS, enter_held  # noqa: E402


def posts(port):  # how many jobs the page has posted to the mock ComfyUI
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/mock/posts", timeout=5) as r:
        return len(json.loads(r.read()))


def quiet(page, port, still=1000):  # how many jobs are posted once none has arrived for `still` ms
    count = posts(port)
    while True:
        page.wait_for_timeout(still)
        now = posts(port)
        if now == count:
            return count
        count = now


def posted(port):  # what each job posted so far writes, in order: a failed check names the job that should not have been posted
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/mock/posts", timeout=5) as r:
        return [p["outputs"] for p in json.load(r)]


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    status = lambda: page.text_content("#status")
    states = lambda: page.eval_on_selector_all("#history li .state", "els => els.map((e) => e.textContent)")

    # 1. The first Klein pass of edit 1 is held, edit 2 waits for its turn, then Esc: nothing is posted
    page.keyboard.press("p"); U.paint_once(page, "a green lamp", [(0.20, 0.75), (0.30, 0.75)])
    enter_held(page, port, U)
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

    # A scene saved under the stop holds both edits and no mark of the stop; an undo step and its redo leave the edit waiting
    _, scene = U.save_scene(page)
    U.check(len(scene["edits"]) == 2 and not any("waits" in e or "state" in e for e in scene["edits"]), f"a scene saved under a stop holds both edits and nothing of the stop: {[sorted(e) for e in scene['edits']]}")
    page.keyboard.press("Control+z"); page.wait_for_timeout(300)
    page.keyboard.press("Control+Shift+Z")
    if not U.until(page, "document.querySelectorAll('#history li').length === 2", 2000):
        page.keyboard.press("Control+y")
    page.wait_for_timeout(500)
    U.check(states() == ["Waits for Enter", "Drawing"] and posts(port) == before, f"an undo step and its redo under the stop post nothing, and the edit still waits: {states()}, {posts(port) - before} posts")

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
    page.keyboard.press("n"); page.keyboard.press("c")
    if not page.is_checked("#whole"):
        page.check("#whole")
    U.paint_once(page, "cup", [(0.6, 0.4), (0.62, 0.45)])
    U.check(U.until(page, f"/^Edit \\w+: cup found under the stroke\\./.test({STATUS})", 30000), f"once SAM's masks are kept the status line says the object is found: {status()}")

    # 5. The stopped edit dropped by a second Esc, then Enter: the edit that waited still runs
    page.keyboard.press("Escape")  # the erase strokes of check 4 go
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.70, 0.75), (0.80, 0.75)])
    enter_held(page, port, U)
    page.keyboard.press("n"); U.paint_once(page, "a blue vase", [(0.70, 0.25), (0.80, 0.25)]); page.keyboard.press("n")
    page.wait_for_function("document.querySelectorAll('#history li').length === 4", timeout=10000)
    page.keyboard.press("Escape"); page.wait_for_timeout(300); page.keyboard.press("Escape")
    U.check(U.until(page, "document.querySelectorAll('#history li').length === 3", 5000) and states() == ["Waits for Enter"],
            f"a second Esc drops the stopped edit, and the other edit still waits: {states()}")
    page.keyboard.press("Enter")
    U.check(U.until(page, U.DONE.format(n=3), 60000) and U.row_words(page)[0] == "a blue vase",
            f"Enter with no edit in progress runs the edit that waited: History {U.row_words(page)}, {states()}")

    # 6. Try another on a History row under a stop: it waits for Enter, then runs after the stopped edit
    page.keyboard.press("n"); page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.70, 0.75), (0.80, 0.75)])
    enter_held(page, port, U)
    page.keyboard.press("Escape")
    before = quiet(page, port)  # a job already on its way when Esc was pressed can still arrive: count once none has for a second
    page.click("#history li:last-child .again"); page.mouse.move(5, 5); page.wait_for_timeout(1500)
    U.check(posts(port) == before and status().endswith("It waits for Enter.") and states() == ["Drawing", "Waits for Enter"],
            f"Try another under a stop posts nothing and says that it waits: {status()} History {states()}, posted since: {posted(port)[before:]}")
    page.evaluate(U.WATCH)
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=4), timeout=120000)
    order = [m.group(1) for line in page.evaluate("window.__lines") for m in [re.match(r"Edit (\d): Paint ", line)] if m]
    U.check(order == ["4", "1"], f"Enter runs the stopped edit, then the other try that waited: passes of edits {order}")
    page.close()

    # 7. No result yet, a stop, then Esc drops the stopped edit: the Generate button stays live for the edit that waits
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.20, 0.75), (0.30, 0.75)])
    enter_held(page, port, U)
    page.keyboard.press("n"); U.paint_once(page, "a blue vase", [(0.45, 0.20), (0.55, 0.20)]); page.keyboard.press("n")
    page.wait_for_function("document.querySelectorAll('#history li').length === 2", timeout=10000)
    page.keyboard.press("Escape"); page.wait_for_timeout(300); page.keyboard.press("Escape")
    U.check(U.until(page, "document.querySelectorAll('#history li').length === 1 && !document.querySelector('#generate').disabled", 5000),
            f"with no result yet, the Generate button stays live while an edit waits: disabled {page.is_disabled('#generate')}")
    page.click("#generate")
    U.check(U.until(page, U.DONE.format(n=1), 60000) and U.row_words(page) == ["a blue vase"], f"and Generate runs it: History {U.row_words(page)}")

    # 8. A stop in force ends when another plate opens: the new plate's first edit runs without Enter
    page.keyboard.press("n"); U.paint_once(page, "a red fire", [(0.20, 0.75), (0.30, 0.75)])
    enter_held(page, port, U)
    page.keyboard.press("Escape")
    page.wait_for_function(f"{STATUS}.startsWith('Stopped')", timeout=10000)
    opened = "[...document.querySelectorAll('#log li span')].filter((e) => e.textContent.startsWith('Plate desk')).length"
    before = page.evaluate(opened)
    U.open_path(page, "plates/desk.mp4")  # the same plate again: OPEN holds before the open has begun, so wait for the open's own line and an empty History
    page.wait_for_function(f"{opened} > {before} && document.querySelector('#opening').hidden && document.querySelectorAll('#history li').length === 0", timeout=60000)
    page.keyboard.press("p"); U.paint_once(page, "a green lamp", [(0.60, 0.40), (0.70, 0.40)]); page.keyboard.press("n")
    U.check(U.until(page, U.DONE.format(n=1), 60000) and U.row_words(page) == ["a green lamp"], f"a stop ends when another plate opens, and its first edit runs without Enter: History {U.row_words(page)}")
    page.close()
