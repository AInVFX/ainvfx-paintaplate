"""Bypassed edits turned back on, as a person returns to a stack made before: each edit comes back from the page's memory,
with « reused » in the log and no new pass. The plate under the edits changes meanwhile (the fluid shot's eye), and its
reopening is held open, so the passes that the eyes start meet it: no pass reads the plate while it is swapped, and no row
stays on Generating. The page runs with no job index (?index=0): what comes back with no pass comes from its memory."""
import re

FLUID = '#history li[data-id="fluid"]'
REUSED = "reused, already made on the same plate with the same edits under it."
SWAPPED = "under the edits: the fluid shot v1"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, query="?blank=0&index=0", errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input")
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)

    # 1. The fluid shot, then a Clean, a Light and a Paint on it, all made
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End")
    U.stroke(page, [(0.45, 0.3), (0.55, 0.2)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    page.keyboard.press("Home")
    edits = (("erase", "the smoke", [(0.45, 0.72), (0.55, 0.7)]), ("light", "", [(0.2, 0.2), (0.24, 0.22)]), ("paint", "a lantern", [(0.75, 0.3), (0.8, 0.32)]))
    for n, (tool, words, pts) in enumerate(edits, start=2):
        page.click(f'.tools [data-tool="{tool}"]')
        U.paint_once(page, words, pts)
        page.keyboard.press("Enter")
        page.wait_for_function(f"({U.DONE.format(n=n)}) || document.querySelector('#ask').open", timeout=120000)
        if page.evaluate("document.querySelector('#ask').open"):  # the mock's erase changes the area around its object: the check asks, and the result is kept
            page.click("#ask-yes")
            page.wait_for_function(U.DONE.format(n=n), timeout=120000)
    U.settled(page)
    U.check(U.row_titles(page) == ["4. Paint", "3. Light", "2. Clean", "1. Fluid"], f"the stack is made: {U.row_titles(page)}")

    def eye(n):  # the eye of History's row n; the rows are newest first
        titles = U.row_titles(page)
        page.click(f"#history li:nth-child({next(k for k, t in enumerate(titles) if t.startswith(f'{n}.')) + 1}) .eye")

    # 2. Edits 4, 3 and 2 bypassed, then the fluid shot: the blank plate is under the edits
    for n in (4, 3, 2):
        eye(n)
    page.click(f"{FLUID} .eye")
    U.wait_log(page, "[...document.querySelectorAll('#log li span')].some((e) => e.textContent.includes('under the edits: the blank plate'))",
               60000, "blank plate under the edits")
    U.settled(page)

    # 3. Edits 4, 3 and 2 back on, then the fluid shot, whose reopening lasts 3 s: the passes the eyes start meet it
    page.evaluate(U.WATCH)
    for n in (4, 3, 2):
        eye(n)
    U.mock_route(port, "/mock/hold", {"output": "spec", "seconds": 3, "times": 1})
    page.click(f"{FLUID} .eye")
    U.wait_log(page, U.added_line(SWAPPED), 60000, "fluid shot under the edits again")
    page.evaluate("window.__calm = 0")
    calm = U.until(page, U.SETTLED, timeout=30000)
    lines = page.evaluate("window.__lines")
    after = lines[max(i for i, t in enumerate(lines) if SWAPPED in t) + 1:]
    failed = [t for t in lines if t.startswith("Error:")]
    U.check(not failed, f"no error while the plate under the edits is swapped: {failed}")
    rows = page.eval_on_selector_all("#history li", "els => els.map((e) => `${e.querySelector('.title').textContent}: ${e.className}`)")
    U.check(calm and not any("busy" in r for r in rows), f"no row stays on Generating once the passes end: {rows}")
    started = sorted({t.split(":")[0] for t in lines[:len(lines) - len(after)] if re.match(r"Edit \d: (Paint|Clean|Light) .*, seed \d+", t)})
    U.check(started and all(f"{n}: {REUSED}" in after for n in started),
            f"each edit that started a pass on the blank plate comes back from the page's memory: {started}, {[t for t in after if 'reused' in t]}")
    posted = [t for t in after if t.startswith(("edit ", "prompt ")) or "Klein edit preview" in t]
    U.check(not posted, f"no edit runs again once the plate is back: {posted}")
    U.check("Fluid shot v1 is back on." in lines, "the fluid shot's eye says what it did, as an edit's eye does")
    U.no_errors(errors, "while the edits come back")
    page.close()
