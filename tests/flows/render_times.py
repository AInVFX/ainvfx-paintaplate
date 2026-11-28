"""A step answered without running keeps no time. The page keeps in its browser storage the seconds each step of a render
took (logic.remember). A step whose jobs come from the job index, or whose outputs all come from ComfyUI's cache, takes
about no time and keeps none. The flow renders an erase from a seed, loads the page again and makes the same erase from
the same seed: its jobs come from the job index, and the times kept stay as they were."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
KEPT = "JSON.parse(localStorage.getItem('paintaplate.step-times') || '{}')"
TAKEN = "window.__lines.filter((t) => t.includes('taken from the job index')).length"


def erase(page, U):
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "the mug", [(0.45, 0.55), (0.5, 0.6)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(("Composite, full size: done in", "Composite, full size: from the job index")), 240000, "the full-size composite")


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, "?blank=0&seed=4242", errors=errors)
    erase(page, U)
    first = page.evaluate(KEPT)
    U.check(any(k.startswith("cleanup|") for k in first) and all(v["total"] > 0 for v in first.values()),
            f"the first erase keeps a time for each step that ran: {sorted(first)}")
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    erase(page, U)
    again, taken = page.evaluate(KEPT), page.evaluate(TAKEN)
    U.check(taken > 0 and again == first, f"the same erase again: {taken} jobs taken from the job index, and the times kept stay as they were: {again}")
    U.no_errors(errors, "with the times kept")
    page.close()
